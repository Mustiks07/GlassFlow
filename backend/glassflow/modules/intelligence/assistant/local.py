"""Deterministic dialog engine: recognized requests → typed facts → short Russian answer.

Used directly in ``local_limited`` mode and as the verified rendering layer for the AI path:
every number in an answer is rendered from a Pricing/KB fact, never typed by a model. It
answers only what it recognizes; unknown prices, services, deadlines and discounts are handed
to the manager with a concrete question instead of a generic refusal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation

from glassflow.contracts.common import Dimensions, Evidence
from glassflow.contracts.cutting import FindRequest

from ..catalog.kb import KnowledgeBase, Product
from ..catalog.mapping import MappingDecision
from ..catalog.matching import COLOR_LEXICON, MatchResult, match_products, query_features
from ..catalog.text import format_decimal, format_money, normalize, stem, stems_match, words
from ..nlu.extract import _COUNT_NUMBER, WORD_NUMBERS, Extraction, extract
from ..ports_consumed import InventoryPort, ServiceUnavailable
from ..pricing import PricingInput, PricingResult, calculate, pricing_input_for, resolve_sides
from .facts import FactSet

MAX_SENTENCES = 4
PRICE_WORDS = re.compile(
    r"сколько(?!\s*(?:дней|дня|времени|ждать|по времени|недел|час|минут))|стоит|стоимост|цен[аыуе]|почем|"
    r"расч[её]т|рассчита|посчита|прайс|по чем|почём|дорого|за м2|за м²"
)
_NAME_NUMBER = re.compile(r"\d+")
RULE_INTENTS = {"installation", "payment", "delivery", "discount"}
UNKNOWN_INTENTS = {"deadline", "availability", "warranty", "compatibility", "contacts"}
UNKNOWN_TOPIC_RU = {
    "deadline": "Сроки изготовления в базе не указаны — их назовет менеджер.",
    "availability": "Наличие товара в базе знаний не указано — его проверит менеджер.",
    "warranty": "Гарантийные условия в базе не указаны — их уточнит менеджер.",
    "compatibility": "Техническую совместимость база знаний не подтверждает — ее проверит менеджер.",
    "contacts": "Адрес и контакты в базе знаний не указаны — их сообщит менеджер.",
}
RULE_FOLLOW_UP = {
    "installation": "Можем рассчитать стекло или зеркало по вашим размерам — пришлите их в мм.",
    "payment": "Предварительный расчет по прайсу могу сделать сразу.",
    "delivery": "Предварительный расчет по прайсу могу сделать сразу.",
    "discount": "Предварительную стоимость по прайсу могу рассчитать сразу.",
}
PRELIMINARY_RU = "Цена предварительная, окончательную стоимость подтверждает менеджер."
SIDES_RU = {
    "all": "по всем 4 сторонам",
    ("long",): "по двум длинным сторонам",
    ("short",): "по двум коротким сторонам",
    ("long1",): "по одной длинной стороне",
    ("short1",): "по одной короткой стороне",
    ("long1", "short1"): "по одной длинной и одной короткой стороне",
    ("top", "bottom"): "по верхней и нижней сторонам",
    ("left", "right"): "по левой и правой сторонам",
}
_SIDE_RU = {"top": "верхней", "bottom": "нижней", "left": "левой", "right": "правой"}


def _sides_ru(edge_sides: str | None, selected: tuple[str, ...]) -> str:
    if edge_sides == "all":
        return SIDES_RU["all"]
    if tuple(selected) in SIDES_RU:
        return SIDES_RU[tuple(selected)]
    named = [_SIDE_RU[s] for s in selected if s in _SIDE_RU]
    if named:
        return "по " + " и ".join(named) + (" стороне" if len(named) == 1 else " сторонам")
    return "по выбранным сторонам"


_resolve_sides = resolve_sides  # kept for imports; the single implementation lives in pricing


@dataclass
class TurnContext:
    product_id: str | None = None
    length_mm: int | None = None
    width_mm: int | None = None
    quantity: int | None = None
    quantity_assumed: bool = False
    invalid_quantity: bool = False
    invalid_dimensions: bool = False
    processing: str = "none"
    edge_sides: str | None = None
    selected_sides: tuple[str, ...] = ()
    price_basis: str = "auto"
    customer_id: str | None = None
    pending_query: str | None = None

    def to_dict(self) -> dict[str, str]:
        data: dict[str, str] = {}
        for key, value in self.__dict__.items():
            if value is None or value == () or value is False:
                continue
            data[key] = ",".join(value) if isinstance(value, tuple) else str(value)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, str] | None) -> "TurnContext":
        context = cls()
        for key, value in (data or {}).items():
            if key in {"length_mm", "width_mm", "quantity"}:
                setattr(context, key, int(value))
            elif key in {"quantity_assumed", "invalid_quantity", "invalid_dimensions"}:
                setattr(context, key, value == "True")
            elif key == "selected_sides":
                context.selected_sides = tuple(v for v in value.split(",") if v)
            elif hasattr(context, key):
                setattr(context, key, value)
        return context


@dataclass
class ToolTrace:
    tool: str
    status: str
    arguments: dict[str, object]
    summary: str
    error_code: str | None = None


@dataclass
class LocalOutcome:
    sentences: list[str]
    status: str  # answered | clarification | manager_handoff | limited
    intent: str
    clarification: str | None
    context: TurnContext
    facts: FactSet
    evidence: list[Evidence]
    tool_calls: list[ToolTrace]
    pricing: PricingResult | None = None
    product: Product | None = None
    mapping: MappingDecision | None = None
    recognized: bool = True
    missing_parameters: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    needs_manager: bool = False
    inventory_status: str = "not_requested"
    candidates: list[dict] = field(default_factory=list)
    inventory_reason_codes: list[str] = field(default_factory=list)
    normalized_dimensions: str | None = None
    catalog_match_reason: str | None = None

    @property
    def answer(self) -> str:
        return " ".join(self.sentences[:MAX_SENTENCES])


def _m(value: Decimal) -> str:
    return format_money(value)


class LocalEngine:
    def __init__(
        self,
        kb: KnowledgeBase,
        mappings: dict[str, MappingDecision],
        *,
        dataset_id: str,
        inventory: InventoryPort | None = None,
    ):
        self.kb = kb
        self.mappings = mappings
        self.dataset_id = dataset_id
        self.inventory = inventory
        self.formats = {p.attributes["sheet_format_mm"] for p in kb.products if "sheet_format_mm" in p.attributes}

    # ------------------------------------------------------------------ helpers
    def _ev(self, record_id: str | None, field_name: str | None) -> Evidence:
        return Evidence(source=self.kb.source, source_version=self.kb.version, record_id=record_id, field=field_name)

    def _ref(self, record_id: str | None, field_name: str | None) -> str:
        return f"kb:{self.kb.version}:{record_id}:{field_name}"

    def _name_facts(self, out: "LocalOutcome", product: Product) -> None:
        """Numbers that are part of a product name (sizes, codes) are facts of that name, not prices."""
        for number in _NAME_NUMBER.findall(product.name):
            out.facts.add("name", int(number), None, self._ref(product.product_id, "название"))
        bulk = product.price("bulk_unit")
        if bulk and bulk.minimum_quantity:
            out.facts.add("threshold", bulk.minimum_quantity, "шт", self._ref(product.product_id, bulk.source_field))

    # ------------------------------------------------------------------ entry point
    def respond(self, text: str, context: TurnContext | None = None, *, inventory_mode: str = "none") -> LocalOutcome:
        context = replace(context) if context else TurnContext()
        ex = extract(text, format_exclusions=self.formats)
        out = LocalOutcome([], "answered", "unknown", None, context, FactSet(), [], [])
        price_signal = bool(
            PRICE_WORDS.search(ex.text)
            or ex.dimensions
            or ex.quantity
            or ex.price_basis != "auto"
            or "tier_prices" in ex.intents
        )
        rule_intents = ex.intents & RULE_INTENTS
        unknown_intents = ex.intents & UNKNOWN_INTENTS
        handled = False

        if ex.model_codes:
            handled = True
            self._models(ex, out)

        product_turn = price_signal or not (
            rule_intents or unknown_intents or ex.unknown_services or ex.model_codes or "accessories" in ex.intents
        )
        match: MatchResult | None = None
        if product_turn and not ex.model_codes:
            match = match_products(self.kb, text)
            text_for_pending = text
            strong = match.status == "exact" and match.candidates[0].score >= 4.0
            if context.pending_query and not strong:
                combined_text = f"{context.pending_query} {text}"
                combined = match_products(self.kb, combined_text)
                if combined.status == "exact" or (
                    combined.status == "ambiguous"
                    and match.status != "exact"
                    and (match.status == "not_found" or len(combined.candidates) < len(match.candidates))
                ):
                    match, text_for_pending = combined, combined_text
            if match.status == "not_found" and context.product_id:
                refined = self._refine_with_context(text, context.product_id, ex)
                if refined is not None:
                    match = refined
            context.pending_query = text_for_pending[-300:] if match.status == "ambiguous" else None
            out.catalog_match_reason = match.reason_code
            if match.reason_code:
                context.product_id = None
            if match.status == "exact" and ex.quantity is None and not ex.invalid_quantity:
                quantity = _quantity_before_name(text, match.product)
                if quantity is not None:
                    count, raw = quantity
                    ex.quantity_source = raw
                    if count <= 0 or count != count.to_integral():
                        ex.invalid_quantity = raw
                    else:
                        ex.quantity = int(count)
            out.tool_calls.append(
                ToolTrace(
                    "search_catalog",
                    "ok",
                    {"query_sha": "local"},
                    f"{match.status}: {[c.product.product_id for c in match.candidates[:4]]}",
                )
            )

        service_focus = bool(
            re.search(
                r"(?:сколько стоит|сколько стоят|цена|цену|почем|стоимость)\s+(?:\w+\s+){0,2}"
                r"(?:фацет|пескостру|гравир|сверл|отверст|закал|фотопечат|печат|триплекс|покрас|шлифов|полиров|гнут|гибк)",
                ex.text,
            )
        )
        service_only = bool(ex.unknown_services) and (service_focus or not ex.dimensions) and not (
            match and match.status == "exact" and ex.price_basis != "auto" and not service_focus
        )
        edge_only = (
            ex.processing == "euro_edge" and not ex.dimensions and context.length_mm is None and not ex.unknown_services
            and not ex.ambiguous_dimensions and not ex.invalid_dimensions
            and ex.price_basis == "auto"
        )
        if ex.unknown_services and service_only:
            handled = True
            self._unknown_services(ex, out, match)
        elif edge_only:
            handled = True
            self._edge_rate(ex, out, match)
        elif match is not None:
            handled = self._product_flow(ex, out, match, price_signal, inventory_mode) or handled

        if rule_intents:
            handled = True
            self._rules(rule_intents, out)
        if unknown_intents and not (out.inventory_status == "checked" and unknown_intents == {"availability"}):
            handled = True
            for intent in sorted(unknown_intents):
                out.sentences.append(UNKNOWN_TOPIC_RU[intent])
                out.facts.add("unknown", intent, None, "policy:no_kb_fact")
            out.needs_manager = True
            if out.status == "answered":
                out.status = "manager_handoff"
        if "accessories" in ex.intents:
            handled = self._accessories(ex, out) or handled
        if not handled:
            if "greeting" in ex.intents:
                out.intent = "greeting"
                out.sentences.append(
                    "Здравствуйте! Напишите, какое стекло, зеркало или фурнитура нужны и размеры в мм — посчитаю "
                    "предварительную стоимость по прайсу."
                )
                out.status = "clarification"
            else:
                out.recognized = False
                out.status = "limited"
                out.intent = "unrecognized"
                out.sentences.append(
                    "Уточните, пожалуйста, товар (вид стекла, цвет, толщину) и размеры в мм — так я дам "
                    "предварительный расчет по прайсу; остальные вопросы передам менеджеру."
                )
                out.clarification = out.sentences[-1]
        self._trim(out)
        out.facts.claim(out.answer, "local", f"renderer:local:{self.kb.version}")
        return out

    def _refine_with_context(self, text: str, product_id: str, ex: Extraction) -> MatchResult | None:
        """«а 8 мм?» / «а калёное?» after a product: re-resolve the previous name with the new attribute."""
        product = self.kb.product(product_id)
        if product is None:
            return None
        query = query_features(text)
        if not (ex.thickness_mm or query.colors or query.families or query.negated_families):
            return None
        base = normalize(product.name)
        if ex.thickness_mm:
            base = re.sub(r"\d+\s*мм", " ", base)
        if query.colors:
            roots = [root for roots in COLOR_LEXICON.values() for root in roots]
            base = " ".join(w for w in base.split() if not any(stems_match(stem(w), root) for root in roots))
        refined = match_products(self.kb, f"{base} {text}")
        return refined if refined.status != "not_found" else None

    # ------------------------------------------------------------------ flows
    def _models(self, ex: Extraction, out: LocalOutcome) -> None:
        out.intent = "mirror_model"
        out.needs_manager = True
        out.status = "manager_handoff"
        missing = {code: rule for code, rule in self.kb.missing_models}
        for code in dict.fromkeys(ex.model_codes):
            label = code.upper()
            if code in missing:
                out.sentences.append(f"Модели {label} в каталоге нет — подобрать вариант и назвать цену поможет менеджер.")
                out.evidence.append(self._ev(missing[code], "правило"))
                out.facts.add("rule", f"missing:{label}", None, self._ref(missing[code], "правило"))
                continue
            rng = self.kb.model_range
            number = int(re.sub(r"\D", "", code))
            if rng and code.startswith(rng[0]) and rng[1] <= number <= rng[2]:
                out.sentences.append("Цена этой модели зеркала в базе не указана — стоимость рассчитает менеджер.")
                out.evidence.append(self._ev(rng[3], "правило"))
                out.facts.add("rule", f"no_price:{label}", None, self._ref(rng[3], "правило"))
            else:
                out.sentences.append(f"Модели {label} нет в базе знаний — ее наличие и цену уточнит менеджер.")
                out.facts.add("unknown", f"model:{label}", None, "policy:no_kb_fact")
        out.sentences.append("Передам указанные параметры менеджеру для индивидуального расчета.")

    def _unknown_services(self, ex: Extraction, out: LocalOutcome, match: MatchResult | None) -> None:
        out.intent = "processing_price"
        out.needs_manager = True
        out.status = "manager_handoff"
        names = ", ".join(dict.fromkeys(ex.unknown_services))
        out.sentences.append(f"Цена услуги «{names}» в базе не указана — ее назовет менеджер.")
        facet_rule = self.kb.rules_for("facet")
        if "фацет" in ex.unknown_services and facet_rule:
            out.evidence.append(self._ev(facet_rule[0].rule_id, "правило"))
        out.facts.add("unknown", names, None, "policy:processing_price_not_in_kb")
        if ex.dimensions:
            out.sentences.append("Передам запрос с размерами детали менеджеру — он рассчитает стоимость обработки.")
        else:
            out.sentences.append("Уточните, пожалуйста, вид стекла или зеркала, толщину и размеры детали — передам расчет менеджеру.")
        out.clarification = out.sentences[-1]
        out.missing_parameters.append("processing_price")

    def _edge_rate(self, ex: Extraction, out: LocalOutcome, match: MatchResult | None) -> None:
        """«Сколько стоит кромка на стекло 6 мм?» — the KB edge rule, not a list of glass prices."""
        out.intent = "edge_rate"
        thickness = sorted(ex.thickness_mm)[0] if ex.thickness_mm else None
        if thickness is None and match is not None and match.status == "exact" and match.product.thickness_mm:
            thickness = match.product.thickness_mm
        noun = "зеркала" if "зеркал" in ex.text else "стекла"
        rule_id = self.kb.edge_rule_id
        if rule_id:
            out.evidence.append(self._ev(rule_id, "правило"))
        if thickness is not None:
            out.facts.add("measure", thickness, "мм", "input")
            rate = self.kb.edge_rate(thickness)
            product = match.product if match is not None and match.status == "exact" else None
            if product is not None and not product.is_hardware:
                out.product, out.mapping = product, self.mappings.get(product.product_id)
                self._name_facts(out, product)
                per_m2 = product.price("per_m2")
                if per_m2 and per_m2.amount is not None:
                    out.facts.add("price", per_m2.amount, "₸/м²", self._ref(product.product_id, per_m2.source_field))
                    out.sentences.append(f"{product.name}: {_m(per_m2.amount)} ₸ за м².")
            if rate is not None:
                out.facts.add("price", rate.amount_per_m, "₸/м", self._ref(rate.rule_id, "правило"))
                out.sentences.append(f"Обработка кромки (евро-кромка) для {noun} {thickness} мм — {_m(rate.amount_per_m)} ₸ за метр.")
                out.sentences.append("Для расчета детали пришлите размеры в мм и стороны обработки.")
                out.clarification = out.sentences[-1]
                out.sentences.append(PRELIMINARY_RU)
                return
            out.sentences.append(f"Цену обработки кромки для {thickness} мм база не содержит — ее назовет менеджер.")
            out.sentences.append("Уточните, пожалуйста, размеры детали — передам расчет менеджеру.")
            out.status, out.needs_manager = "manager_handoff", True
            out.facts.add("unknown", f"edge_{thickness}mm", None, "policy:edge_rate_not_in_kb")
            return
        if self.kb.edge_rates:
            parts = []
            for rate in self.kb.edge_rates:
                parts.append(f"{rate.thickness_mm} мм — {_m(rate.amount_per_m)} ₸ за метр")
                out.facts.add("price", rate.amount_per_m, "₸/м", self._ref(rate.rule_id, "правило"))
                out.facts.add("measure", rate.thickness_mm, "мм", self._ref(rate.rule_id, "правило"))
            out.sentences.append(f"Евро-кромка по прайсу: {', '.join(parts)}; для других толщин цену назовет менеджер.")
        else:
            out.sentences.append("Ставки обработки кромки в базе нет — ее назовет менеджер.")
            out.needs_manager = True
        out.sentences.append("Уточните, пожалуйста, толщину стекла и размеры детали.")
        out.clarification = out.sentences[-1]
        out.status = "clarification"

    def _rules(self, intents: set[str], out: LocalOutcome) -> None:
        used: set[str] = set()
        if out.intent == "unknown":
            out.intent = "rule:" + ",".join(sorted(intents))
        for intent in ("installation", "payment", "delivery", "discount"):
            if intent not in intents:
                continue
            rules = self.kb.rules_for(intent)
            if rules:
                rule = rules[0]
                if rule.rule_id in used:
                    continue
                used.add(rule.rule_id)
                text = rule.text.strip()
                if intent == "discount" and "менеджер" not in text.lower():
                    text += " Условия называет менеджер."
                out.sentences.append(text)
                follow_up = RULE_FOLLOW_UP.get(intent)
                if follow_up and follow_up not in out.sentences:
                    out.sentences.append(follow_up)
                out.evidence.append(self._ev(rule.rule_id, "правило"))
                out.facts.add("rule", rule.rule_id, None, self._ref(rule.rule_id, "правило"))
            elif intent == "discount":
                out.sentences.append("Скидки и акции ассистент не обещает — условия называет только менеджер.")
                out.facts.add("rule", "discount_policy", None, "policy:no_discount_promises")
            else:
                out.sentences.append("Эти условия в базе не описаны — их согласует менеджер.")
                out.facts.add("unknown", intent, None, "policy:no_kb_fact")
                out.needs_manager = True

    def _accessories(self, ex: Extraction, out: LocalOutcome) -> bool:
        items = recommend_accessories(self.kb, ex.text)
        out.tool_calls.append(ToolTrace("recommend_accessories", "ok", {}, f"{len(items)} items"))
        if not items:
            return False
        parts = []
        for product in items[:3]:
            self._name_facts(out, product)
            retail = product.price("retail_unit")
            if retail and retail.amount is not None:
                parts.append(f"{product.name} — {_m(retail.amount)} ₸")
                out.facts.add("price", retail.amount, "₸/шт", self._ref(product.product_id, retail.source_field))
            else:
                parts.append(product.name)
        out.sentences.append("Из сопутствующих позиций в каталоге есть: " + "; ".join(parts) + ".")
        out.sentences.append("Техническую совместимость с вашим изделием подтвердит менеджер.")
        if out.intent == "unknown":
            out.intent = "accessories"
        return True

    # ------------------------------------------------------------------ product flow
    def _product_flow(self, ex, out, match: MatchResult, price_signal: bool, inventory_mode: str) -> bool:
        context = out.context
        product: Product | None = None
        if match.status == "exact":
            product = match.product
            if context.product_id and context.product_id != product.product_id:
                context.processing = context.processing if ex.processing == "none" else ex.processing
            context.product_id = product.product_id
            out.alternatives = [c.product.name for c in match.candidates[1:4] if c.score > 0]
            for flag in match.candidates[0].soft:
                if flag == "thickness_not_in_catalog" and ex.thickness_mm:
                    out.assumptions.append(
                        f"В каталоге «{product.name}» без толщины; применимость к {sorted(ex.thickness_mm)[0]} мм подтвердит менеджер."
                    )
        elif match.status == "ambiguous":
            self._update_params(ex, context, out)
            self._ambiguous(ex, out, match)
            return True
        elif context.product_id and not match.reason_code and (
            ex.dimensions or ex.quantity or ex.invalid_quantity or ex.invalid_dimensions or ex.ambiguous_dimensions
            or ex.processing != "none" or ex.price_basis != "auto" or ex.edge_sides is not None
        ):
            product = self.kb.product(context.product_id)
        if product is None:
            if price_signal and not (ex.intents & (RULE_INTENTS | UNKNOWN_INTENTS)):
                out.intent = "product_price"
                out.status = "manager_handoff"
                out.needs_manager = True
                out.sentences.append("Такой позиции нет в базе KSM — ее наличие и цену уточнит менеджер.")
                out.facts.add("unknown", "product_not_in_kb", None, "policy:not_in_kb")
                out.sentences.append("Если нужно стекло или зеркало из каталога, напишите вид, цвет, толщину и размеры в мм.")
                out.recognized = bool(ex.dimensions or ex.intents)
                return True
            return False

        out.product = product
        out.mapping = self.mappings.get(product.product_id)
        out.evidence.append(self._ev(product.product_id, "название"))
        self._name_facts(out, product)
        self._update_params(ex, context, out)
        if out.status == "clarification" and out.missing_parameters:
            return True
        if product.is_hardware:
            self._hardware(ex, out, product)
        else:
            self._material(ex, out, product, inventory_mode)
        for note in out.assumptions:
            if note.startswith("В каталоге") and len(out.sentences) < MAX_SENTENCES:
                out.sentences.append(note)
        return True

    def _update_params(self, ex: Extraction, context: TurnContext, out: LocalOutcome) -> None:
        if ex.invalid_quantity:
            context.invalid_quantity = True
        elif ex.quantity is not None:
            context.invalid_quantity = False
        if context.invalid_quantity:
            context.quantity = None
            question = (f"Укажите положительное целое количество вместо «{ex.invalid_quantity}»." if ex.invalid_quantity
                        else "Укажите положительное целое количество: прежнее значение было некорректным.")
            out.sentences.append(question)
            out.clarification = question
            out.status = "clarification"
            out.missing_parameters.append("quantity")
        if ex.ambiguous_dimensions or ex.invalid_dimensions:
            context.invalid_dimensions = True
            context.length_mm = context.width_mm = None
            raw = (ex.ambiguous_dimensions or ex.invalid_dimensions)[0]
            question = (f"Укажите положительные длину и ширину вместо «{raw}», с единицами мм, см или м."
                        if ex.invalid_dimensions else f"Уточните единицы размера «{raw}»: это мм, см или м?")
            if not out.clarification:
                out.sentences.append(question)
                out.clarification = question
            out.status = "clarification"
            out.missing_parameters.append("dimensions_invalid" if ex.invalid_dimensions else "dimensions_unit")
        if ex.dimensions and not (ex.ambiguous_dimensions or ex.invalid_dimensions):
            context.invalid_dimensions = False
            first = ex.dimensions[0]
            context.length_mm, context.width_mm = first.length_mm, first.width_mm
            out.normalized_dimensions = first.normalized_text
            out.facts.add("dimension", first.length_mm, "мм", "input:normalized")
            out.facts.add("dimension", first.width_mm, "мм", "input:normalized")
            if first.source_unit != "mm":
                out.assumptions.append(f"Размер «{first.source_text}» переведен в {first.normalized_text}.")
            elif not first.explicit_unit:
                out.assumptions.append(f"Размер «{first.source_text}» принят в миллиметрах.")
            if len(ex.dimensions) > 1:
                out.assumptions.append("В запросе несколько размеров; расчет выполнен для первого.")
        elif context.invalid_dimensions and not (ex.ambiguous_dimensions or ex.invalid_dimensions):
            if not out.clarification:
                out.clarification = "Укажите положительные длину и ширину с единицами: прежний размер требует исправления."
                out.sentences.append(out.clarification)
            out.status = "clarification"
            out.missing_parameters.append("dimensions_invalid")
        if ex.quantity is not None:
            context.quantity, context.quantity_assumed = ex.quantity, False
        if ex.processing_negated:
            context.processing, context.edge_sides, context.selected_sides = "none", None, ()
        elif ex.processing != "none":
            context.processing = ex.processing
        if ex.edge_sides is not None and context.processing == "euro_edge":
            context.edge_sides, context.selected_sides = ex.edge_sides, ex.selected_sides
        if ex.price_basis != "auto":
            context.price_basis = ex.price_basis
        elif ex.dimensions:
            context.price_basis = "auto"

    def _ambiguous(self, ex: Extraction, out: LocalOutcome, match: MatchResult) -> None:
        options = [c.product for c in match.candidates[:4]]
        out.intent = "product_price"
        out.status = "clarification"
        out.alternatives = [p.name for p in options]
        attribute = _distinguishing_attribute(options)
        basis = ex.price_basis
        rendered: list[str] = []
        for product in options:
            self._name_facts(out, product)
            price_text = self._short_price(product, basis, out.facts)
            rendered.append(f"{product.name} — {price_text}" if price_text else product.name)
        same_price = len({self._short_price(p, basis, FactSet_dummy()) for p in options}) == 1 and rendered
        if len(options) == 1:
            out.sentences.append(f"В каталоге есть «{options[0].name}»; соответствие вашему запросу пока не подтверждено.")
            question = "Вы имеете в виду эту позицию или другую модель? Укажите точный артикул или название."
            attribute = "модель или точное название"
        elif same_price and options[0].is_hardware:
            out.sentences.append(f"{self._common_name(options)}: {self._short_price(options[0], basis, out.facts)}.")
            question = f"Есть варианты: {', '.join(p.name for p in options)} — уточните нужный."
        else:
            out.sentences.append(f"В каталоге несколько вариантов: {'; '.join(rendered)}.")
            question = f"Уточните, пожалуйста, {attribute}."
        out.sentences.append(question)
        out.clarification = question
        out.missing_parameters.append(attribute)
        for product in options:
            out.evidence.append(self._ev(product.product_id, "название"))

    def _common_name(self, options: list[Product]) -> str:
        first = options[0].name
        prefix = first
        for product in options[1:]:
            while not product.name.startswith(prefix) and prefix:
                prefix = prefix[:-1]
        if prefix != first and first[len(prefix):len(prefix) + 1] not in {" ", ","}:
            cut = max(prefix.rfind(","), prefix.rfind(" "))
            prefix = prefix[:cut] if cut > 0 else prefix
        prefix = prefix.rstrip(" ,(")
        return prefix or first

    def _short_price(self, product: Product, basis: str, facts) -> str | None:
        if product.is_hardware:
            retail, bulk = product.price("retail_unit"), product.price("bulk_unit")
            parts = []
            if retail and retail.amount is not None:
                parts.append(f"{_m(retail.amount)} ₸ в розницу")
                facts.add("price", retail.amount, "₸/шт", self._ref(product.product_id, retail.source_field))
            if bulk and bulk.amount is not None:
                parts.append(f"{_m(bulk.amount)} ₸ от {bulk.minimum_quantity} шт")
                facts.add("price", bulk.amount, "₸/шт", self._ref(product.product_id, bulk.source_field))
            return ", ".join(parts) or None
        per_m2, sheet = product.price("per_m2"), product.price("per_sheet")
        if basis == "per_sheet":
            if sheet and sheet.amount is not None:
                facts.add("price", sheet.amount, "₸/лист", self._ref(product.product_id, sheet.source_field))
                return f"лист {_m(sheet.amount)} ₸"
            return "цена листа не указана"
        if per_m2 and per_m2.amount is not None:
            facts.add("price", per_m2.amount, "₸/м²", self._ref(product.product_id, per_m2.source_field))
            return f"{_m(per_m2.amount)} ₸/м²"
        if sheet and sheet.amount is not None:
            facts.add("price", sheet.amount, "₸/лист", self._ref(product.product_id, sheet.source_field))
            return f"лист {_m(sheet.amount)} ₸ (ставки за м² нет)"
        return None

    def _hardware(self, ex: Extraction, out: LocalOutcome, product: Product) -> None:
        out.intent = "hardware_price"
        context = out.context
        if ex.dimensions:
            out.assumptions.append("Размеры не применяются к штучной фурнитуре.")
        retail, bulk = product.price("retail_unit"), product.price("bulk_unit")
        threshold = bulk.minimum_quantity if bulk else None
        quantity = context.quantity if ex.quantity is not None or (context.quantity and not context.quantity_assumed) else None
        if quantity is not None:
            out.facts.add("quantity", quantity, "шт", "context")
        if quantity is not None and not ex.tier_inquiry:
            result = self._price(PricingInput(product, quantity=quantity, price_basis="unit"), out)
            if result.lines:
                line = result.lines[0]
                tier = f"цена от {threshold} шт" if threshold and quantity >= threshold else "розничная цена"
                out.sentences.append(
                    f"{product.name}: {quantity} шт × {_m(line.unit_price)} ₸ = {_m(line.amount)} ₸ ({tier})."
                )
                if threshold and quantity < threshold and bulk and bulk.amount is not None:
                    out.sentences.append(f"При заказе от {threshold} шт — {_m(bulk.amount)} ₸ за штуку.")
                    out.facts.add("price", bulk.amount, "₸/шт", self._ref(product.product_id, bulk.source_field))
                out.sentences.append(PRELIMINARY_RU)
            else:
                out.sentences.append(result.unknowns[0].message_ru)
                if retail and retail.amount is not None and threshold and quantity >= threshold:
                    out.sentences.append(f"Розничная цена — {_m(retail.amount)} ₸ за штуку (до {threshold} шт).")
                    out.facts.add("price", retail.amount, "₸/шт", self._ref(product.product_id, retail.source_field))
                out.status = "manager_handoff"
                out.needs_manager = True
            return
        parts = []
        if retail and retail.amount is not None:
            parts.append(f"{_m(retail.amount)} ₸ за штуку в розницу")
            out.facts.add("price", retail.amount, "₸/шт", self._ref(product.product_id, retail.source_field))
            out.evidence.append(self._ev(product.product_id, retail.source_field))
        if bulk and bulk.amount is not None:
            parts.append(f"{_m(bulk.amount)} ₸ за штуку при заказе от {threshold} шт")
            out.facts.add("price", bulk.amount, "₸/шт", self._ref(product.product_id, bulk.source_field))
            out.evidence.append(self._ev(product.product_id, bulk.source_field))
        if parts:
            out.sentences.append(f"{product.name}: {', '.join(parts)}.")
        else:
            out.sentences.append(f"Цены «{product.name}» в базе нет — ее назовет менеджер.")
            out.status = "manager_handoff"
            out.needs_manager = True
        if bulk is not None and bulk.amount is None and threshold:
            out.sentences.append(f"Цены при заказе от {threshold} шт в базе нет — ее назовет менеджер.")
            out.needs_manager = True
        out.sentences.append(PRELIMINARY_RU)

    def _price(self, request: PricingInput, out: LocalOutcome) -> PricingResult:
        result = calculate(self.kb, request)
        out.tool_calls.append(
            ToolTrace(
                "calculate_quote",
                "ok",
                {
                    "catalog_product_id": request.product.product_id,
                    "length_mm": request.length_mm,
                    "width_mm": request.width_mm,
                    "quantity": request.quantity,
                    "processing": request.processing_kind,
                },
                f"total={result.total} unknown={[u.reason_code for u in result.unknowns]}",
            )
        )
        for line in result.lines:
            out.facts.add("line", line.amount, "₸", f"pricing:{line.component}")
            out.facts.add("price", line.unit_price, f"₸/{line.unit}", f"pricing:{line.component}:rate")
            if line.measure_per_unit is not None:
                out.facts.add("measure", line.measure_per_unit, line.unit, f"pricing:{line.component}:measure")
            out.evidence.extend(line.evidence)
        if result.total is not None:
            out.facts.add("total", result.total, "₸", "pricing:total")
        if result.known_subtotal is not None:
            out.facts.add("total", result.known_subtotal, "₸", "pricing:known_subtotal")
        return result

    def _material(self, ex: Extraction, out: LocalOutcome, product: Product, inventory_mode: str) -> None:
        context = out.context
        per_m2, sheet = product.price("per_m2"), product.price("per_sheet")
        has_dims = context.length_mm is not None
        if context.price_basis == "per_sheet" and (ex.price_basis == "per_sheet" or not ex.dimensions):
            out.intent = "sheet_price"
            if sheet and sheet.amount is not None:
                out.facts.add("price", sheet.amount, "₸/лист", self._ref(product.product_id, sheet.source_field))
                out.evidence.append(self._ev(product.product_id, sheet.source_field))
                quantity = context.quantity if not context.quantity_assumed else None
                if quantity:
                    result = self._price(PricingInput(product, quantity=quantity, price_basis="per_sheet"), out)
                    out.pricing = result
                    out.sentences.append(
                        f"Целый лист «{product.name}» стоит {_m(sheet.amount)} ₸; за {quantity} шт — {_m(result.total)} ₸."
                    )
                else:
                    out.sentences.append(f"Целый лист «{product.name}» стоит {_m(sheet.amount)} ₸.")
                out.sentences.append(PRELIMINARY_RU)
            else:
                out.sentences.append(f"Цены целого листа «{product.name}» в базе нет — ее назовет менеджер.")
                if per_m2 and per_m2.amount is not None:
                    out.sentences.append(f"По прайсу есть ставка {_m(per_m2.amount)} ₸ за м².")
                    out.facts.add("price", per_m2.amount, "₸/м²", self._ref(product.product_id, per_m2.source_field))
                out.status = "manager_handoff"
                out.needs_manager = True
            return
        if not has_dims:
            out.intent = "unit_price"
            parts = []
            if per_m2 and per_m2.amount is not None:
                parts.append(f"{_m(per_m2.amount)} ₸ за м²")
                out.facts.add("price", per_m2.amount, "₸/м²", self._ref(product.product_id, per_m2.source_field))
                out.evidence.append(self._ev(product.product_id, per_m2.source_field))
            if sheet and sheet.amount is not None and (context.price_basis != "per_m2" or not parts):
                parts.append(f"целый лист — {_m(sheet.amount)} ₸")
                out.facts.add("price", sheet.amount, "₸/лист", self._ref(product.product_id, sheet.source_field))
                out.evidence.append(self._ev(product.product_id, sheet.source_field))
            if parts and per_m2 and per_m2.amount is not None:
                out.sentences.append(f"{product.name}: {', '.join(parts)}.")
                out.sentences.append(PRELIMINARY_RU)
            elif parts and context.price_basis == "per_m2":
                out.sentences.append(
                    f"Ставки за м² для «{product.name}» в базе нет — есть только цена целого листа; стоимость детали "
                    "рассчитает менеджер."
                )
                out.sentences.append("Передам запрос менеджеру для индивидуального расчета.")
                out.assumptions.append(f"Известная цена целого листа: {_m(sheet.amount)} ₸.")
                out.missing_parameters.append("per_m2_price")
                out.needs_manager = True
                out.status = "manager_handoff"
            elif parts:
                out.sentences.append(
                    f"{product.name}: {parts[0]}; ставки за м² в базе нет, поэтому стоимость детали рассчитает менеджер."
                )
                out.needs_manager = True
                out.status = "manager_handoff"
            else:
                out.sentences.append(f"Цены «{product.name}» в базе нет — ее назовет менеджер.")
                out.needs_manager = True
                out.status = "manager_handoff"
            if context.quantity and not context.quantity_assumed and context.price_basis == "auto" and parts:
                question = f"Для общей стоимости {context.quantity} деталей укажите длину и ширину с единицами измерения."
                out.sentences.append(question)
                out.clarification = question
                out.status = "clarification"
                out.missing_parameters.append("dimensions")
            if ex.processing != "none":
                self._processing_without_dims(ex, out, product)
            return

        out.intent = "quote"
        if context.quantity is None:
            context.quantity, context.quantity_assumed = 1, True
            out.assumptions.append("Количество не указано — расчет за 1 деталь.")
        request, edge_unknown = pricing_input_for(
            product,
            length_mm=context.length_mm,
            width_mm=context.width_mm,
            quantity=context.quantity,
            processing=context.processing,
            edge_sides=context.edge_sides,
            selected_sides=context.selected_sides,
            price_basis="per_m2",
        )
        sides_unknown = edge_unknown and context.edge_sides is None
        selected_unknown = edge_unknown and not sides_unknown
        if edge_unknown:  # glass now; the all-sides variant is shown as a conditional, not assumed
            request = replace(request, processing_kind="none", sides="all", selected_sides=())
        result = self._price(request, out)
        out.pricing = result
        out.facts.add("dimension", context.length_mm, "мм", "context")
        out.facts.add("dimension", context.width_mm, "мм", "context")
        out.facts.add("quantity", context.quantity, "шт", "context")
        dims_text = f"{context.length_mm}×{context.width_mm} мм"
        qty_text = f", {context.quantity} шт" if context.quantity != 1 else ""
        glass = next((line for line in result.lines if line.component == "glass"), None)
        edge = next((line for line in result.lines if line.component == "edge"), None)
        if glass is None:
            reason = next((u for u in result.unknowns if u.component == "glass"), None)
            if sheet and sheet.amount is not None:
                # The asked price is unknown: the client text carries no numbers (no invented or echoed
                # figures); the known sheet price stays in the working card and the quote.
                out.sentences.append(
                    f"Ставки за м² для «{product.name}» в базе нет — есть только цена целого листа, поэтому стоимость "
                    "детали рассчитает менеджер."
                )
                out.sentences.append("Передам указанные параметры менеджеру для индивидуального расчета.")
                out.facts.add("price", sheet.amount, "₸/лист", self._ref(product.product_id, sheet.source_field))
                out.assumptions.append(f"Известная цена целого листа: {_m(sheet.amount)} ₸ (ставка за м² не выводится из листа).")
            else:
                out.sentences.append(reason.message_ru if reason else f"Стоимость «{product.name}» рассчитает менеджер.")
            out.status = "manager_handoff"
            out.needs_manager = True
            out.missing_parameters.append("per_m2_price")
            self._inventory(out, product, inventory_mode)
            return
        area = format_decimal(glass.measure_per_unit)
        if context.quantity == 1:
            glass_text = f"{product.name}, {dims_text}: {area} м² × {_m(glass.unit_price)} ₸ = {_m(glass.amount)} ₸"
        else:
            glass_text = (
                f"{product.name}, {dims_text}{qty_text}: {area} м² × {_m(glass.unit_price)} ₸ × {context.quantity} = "
                f"{_m(glass.amount)} ₸"
            )
        if edge is None and not result.unknowns and not sides_unknown and not selected_unknown:
            out.sentences.append(glass_text + ".")
            out.sentences.append(PRELIMINARY_RU)
        else:
            out.sentences.append(glass_text + ".")
            if edge is not None:
                sides_ru = _sides_ru(context.edge_sides, tuple(context.selected_sides))
                edge_len = format_decimal(edge.measure_per_unit)
                mult = f" × {context.quantity}" if context.quantity != 1 else ""
                out.sentences.append(
                    f"Евро-кромка {sides_ru}: {edge_len} м × {_m(edge.unit_price)} ₸{mult} = {_m(edge.amount)} ₸."
                )
            for unknown in result.unknowns:
                out.sentences.append(unknown.message_ru)
                out.needs_manager = True
            if sides_unknown or selected_unknown:
                self._conditional_edge(out, product, context)
            elif result.total is not None:
                out.sentences.append(f"Итого предварительно {_m(result.total)} ₸; окончательную стоимость подтверждает менеджер.")
            if result.unknowns:
                out.status = "manager_handoff"
        self._inventory(out, product, inventory_mode)

    def _conditional_edge(self, out: LocalOutcome, product: Product, context: TurnContext) -> None:
        variant = calculate(
            self.kb,
            PricingInput(product, context.length_mm, context.width_mm, context.quantity, "euro_edge", "all"),
        )
        edge = next((line for line in variant.lines if line.component == "edge"), None)
        question = "Уточните, по каким сторонам нужна кромка."
        if edge is not None and variant.total is not None:
            out.facts.add("line", edge.amount, "₸", "pricing:edge_all_sides_variant")
            out.facts.add("total", variant.total, "₸", "pricing:total_all_sides_variant")
            question = (
                f"Если кромка нужна по всем 4 сторонам — {_m(edge.amount)} ₸, итого {_m(variant.total)} ₸; "
                "уточните, по каким сторонам обрабатывать."
            )
        out.sentences.append(question)
        out.clarification = question
        out.status = "clarification"
        out.missing_parameters.append("edge_sides")

    def _processing_without_dims(self, ex: Extraction, out: LocalOutcome, product: Product) -> None:
        if ex.processing == "euro_edge":
            rate = self.kb.edge_rate(product.thickness_mm)
            if rate is not None:
                out.sentences.append(f"Евро-кромка для {rate.thickness_mm} мм — {_m(rate.amount_per_m)} ₸ за метр.")
                out.facts.add("price", rate.amount_per_m, "₸/м", self._ref(rate.rule_id, "правило"))
            else:
                out.sentences.append("Ставки кромки для этой толщины в базе нет — ее назовет менеджер.")
                out.needs_manager = True
        out.sentences.append("Пришлите размеры детали в мм — посчитаю стоимость.")
        out.clarification = out.sentences[-1]

    def _inventory(self, out: LocalOutcome, product: Product, inventory_mode: str) -> None:
        context = out.context
        if inventory_mode == "none" or context.length_mm is None:
            return
        mapping = out.mapping
        if mapping is None or mapping.status != "confirmed" or not mapping.material_id:
            out.inventory_status = "mapping_required"
            out.inventory_reason_codes.append(f"mapping_{mapping.status if mapping else 'missing'}")
            out.tool_calls.append(ToolTrace("resolve_material", "ok", {"catalog_product_id": product.product_id},
                                            f"{mapping.status if mapping else 'missing'}"))
            if len(out.sentences) < MAX_SENTENCES:
                out.sentences.append(
                    "Подбор остатка не выполнялся: складское соответствие этой позиции не подтверждено."
                )
            return
        out.tool_calls.append(ToolTrace("resolve_material", "ok", {"catalog_product_id": product.product_id}, mapping.material_id))
        if self.inventory is None:
            out.inventory_status = "service_unavailable"
            out.tool_calls.append(ToolTrace("find_remnants", "unavailable", {}, "inventory port not wired", "SERVICE_UNAVAILABLE"))
            return
        request = FindRequest(
            dataset_id=self.dataset_id,
            material_id=mapping.material_id,
            dimensions=Dimensions(length_mm=context.length_mm, width_mm=context.width_mm),
            premium=False,
            inventory_mode="replan" if inventory_mode == "replan" else "free_whole_remnants",
        )
        try:
            found = self.inventory.find_candidates(request)
        except ServiceUnavailable as exc:
            out.inventory_status = "service_unavailable"
            out.tool_calls.append(ToolTrace("find_remnants", "unavailable", {}, str(exc), "SERVICE_UNAVAILABLE"))
            return
        out.inventory_status = "checked"
        out.inventory_reason_codes = list(found.reason_codes)
        out.tool_calls.append(
            ToolTrace("find_remnants", "ok", {"material_id": mapping.material_id}, f"{len(found.candidates)} candidates")
        )
        out.candidates = [candidate.model_dump() for candidate in found.candidates]
        if found.candidates:
            best = found.candidates[0]
            rot = ", с поворотом" if best.rot == 1 else ""
            out.facts.add("remnant", best.remnant_id, None, f"inventory:{best.remnant_id}:v{best.remnant_version}")
            sentence = (
                f"Подходит свободный остаток {best.remnant_id} ({best.location_raw}), положение ({best.x_mm}, {best.y_mm}){rot}; "
                "резерв — только после подтверждения."
            )
        else:
            sentence = "Свободного подходящего остатка при текущих резервах нет; это не исключает перепланирования."
        if len(out.sentences) >= MAX_SENTENCES:
            out.sentences.insert(MAX_SENTENCES - 1, sentence)
        else:
            out.sentences.append(sentence)

    def _trim(self, out: LocalOutcome) -> None:
        seen: list[str] = []
        for sentence in out.sentences:
            if sentence not in seen:
                seen.append(sentence)
        if len(seen) > MAX_SENTENCES and PRELIMINARY_RU in seen:
            seen.remove(PRELIMINARY_RU)
            seen[0] = seen[0].rstrip(".") + " — предварительно."
        out.sentences = seen[:MAX_SENTENCES]


def _quantity_before_name(text: str, product: Product) -> tuple[Decimal, str] | None:
    """«4 полкодержателя», «две лупы»: a count directly before a word of the product name."""
    name_stems = {stem(w) for w in words(product.name) if not w.isdigit() and len(w) > 3}
    value = normalize(text)
    for match in re.finditer(r"(?<![\w\d.,x/+\-−])(" + _COUNT_NUMBER + r"|(?:минус\s+)?(?:" + "|".join(WORD_NUMBERS) + r"))\s+([а-яa-z-]+)", value):
        raw, word = match.groups()
        if re.match(r"(?:мм|см|м|шт|штук|лист|кв|м2|м²|тг|тенге|вт)\b", word):
            continue
        if any(stems_match(stem(word), name_stem) for name_stem in name_stems):
            token = raw.removeprefix("минус ")
            try:
                number = Decimal(WORD_NUMBERS[token]) if token in WORD_NUMBERS else Decimal(token.replace(" ", "").replace(",", ".").replace("−", "-"))
                if "/" in token or "e" in token:
                    number = Decimal(0)
            except InvalidOperation:
                number = Decimal(0)
            return (-number if raw.startswith("минус ") else number), match.group(0)
    return None


class FactSet_dummy:  # noqa: N801 - throwaway sink for price-equality checks
    def add(self, *args, **kwargs):
        return None


def _distinguishing_attribute(options: list[Product]) -> str:
    if all(p.is_hardware for p in options):
        return "модель или размер"
    keys = [
        ("thickness_mm", "толщину"),
        ("families", "вид стекла (обычное, калёное, рифлёное)"),
        ("color", "цвет"),
        ("sheet_format_mm", "формат листа"),
        ("variant", "вариант"),
    ]
    labels = [label for key, label in keys if len({p.attributes.get(key, "") for p in options}) > 1]
    if not labels:
        return "нужную позицию"
    return " и ".join(labels[:2])


_PURPOSE = [
    (r"зеркал", ["для зеркал", "крепления зеркала"]),
    (r"подсвет|led|светодиод|сенсор|выключател", ["питани", "переключател", "динамик"]),
    (r"полк", ["полкодержател"]),
    (r"двер|створк|петл|навес|шкаф", ["навес"]),
    (r"фасад|рамк|рамоч", ["фасад"]),
    (r"клей|приклеить|силикон|клеить", ["силикон"]),
]


def recommend_accessories(kb: KnowledgeBase, text: str) -> list[Product]:
    """KB hardware whose *name* relates to the stated purpose. No compatibility guarantee."""
    from ..catalog.text import normalize

    value = normalize(text)
    roots: list[str] = []
    for pattern, product_roots in _PURPOSE:
        if re.search(pattern, value):
            roots.extend(product_roots)
    if not roots:
        return []
    items = []
    for product in kb.products:
        if not product.is_hardware:
            continue
        name = normalize(product.name)
        if any(root in name for root in roots):
            items.append(product)
    return items
