"""Dialog quality control: is the price in the manager's reply correct for the client question?

The check uses the same catalog matcher and Pricing service as the assistant. It interprets
each money value in context (rate per m², sheet, retail, bulk, order total); dimensions,
thickness, model codes, quantities and percentages are not prices. The reference comes from
the KB/Pricing, never from an answer key. Verdicts:

- OK — every recognized price equals the applicable reference (absolute tolerance 0.5 ₸);
- ERROR + correct — a price contradicts a known reference;
- NEEDS_REVIEW — the product/price cannot be determined from the KB, or an ambiguous
  question has no single provable correction (internal state; exports must not turn it into
  OK/ERROR, and the correction is never chosen by match score).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal

from glassflow.contracts.common import Evidence
from glassflow.contracts.intelligence import DialogVerdict, PriceMention

from ..catalog.kb import KnowledgeBase, Product
from ..catalog.matching import UNSUPPORTED_IDENTIFIERS, match_products
from ..catalog.text import normalize
from ..nlu.extract import extract
from ..pricing import PricingInput, calculate, pricing_input_for

TOLERANCE = Decimal("0.5")
_MONEY = re.compile(
    r"(?<![\w.,])(?<!\d\s)(\d{1,3}(?:[   ]\d{3})+|\d+)(?:[.,](\d{1,2}))?\s*(?:тг|₸|тенге|тнг|kzt)(?![a-zа-я])",
    re.IGNORECASE,
)
_BARE_NUMBER = re.compile(r"(?<![\w.,x-])(?<!\d\s)(\d{1,3}(?:[   ]\d{3})+|\d{3,})(?:[.,](\d{1,2}))?(?![\w%x]|\s*(?:мм|см|шт|%|x))")


@dataclass
class _Mention:
    amount: Decimal
    raw: str
    meaning: str
    start: int
    clause: str = ""


def money_string(value: Decimal) -> str:
    value = value.quantize(Decimal("0.01"))
    text = f"{value:f}"
    return text[:-3] if text.endswith(".00") else text


def _strip_product_name(text: str, product: Product | None) -> str:
    """Blank out the product name (tolerant to missing commas/brackets) and its sheet format."""
    if product is None:
        return text
    tokens = re.findall(r"[a-zа-я0-9]+", normalize(product.name))
    if tokens:
        pattern = r"[\s,.:;()+\-x×]*".join(re.escape(token) for token in tokens)
        text = re.sub(pattern, lambda m: " " * len(m.group(0)), text, count=1)
    if "sheet_format_mm" in product.attributes:
        text = re.sub(r"лист\w*\s*\d{3,5}\s*x\s*\d{3,5}", lambda m: " " * len(m.group(0)), text)
    return text


def _clause(text: str, start: int, end: int) -> str:
    """The clause around a number: bounded by sentence/clause separators, not decimal commas."""
    left = max(text.rfind(sep, 0, start) for sep in (",", ";", ".", "!", "?", "\n"))
    right_candidates = [text.find(sep, end) for sep in (",", ";", ".", "!", "?", "\n")]
    right = min([pos for pos in right_candidates if pos >= 0], default=len(text))
    return text[left + 1 : right]


def _meaning(clause: str) -> str:
    if re.search(r"(?:/|за|за 1)\s*(?:м2|м²|кв\.?\s?м|квадрат)", clause):
        return "per_m2"
    if re.search(r"от\s+\d+\s*(?:шт|штук)|оптом|при заказе от|оптов", clause):
        return "bulk_unit"
    if re.search(r"в розниц|розничн|за штуку|/\s*шт|за шт\b", clause):
        return "retail_unit"
    if re.search(r"\bлист", clause):
        return "per_sheet"
    if re.search(r"итого|всего|получится|выйдет|общая|за все|стоимость заказа|за \d+ (?:шт|штук|детал)|за детал", clause):
        return "total"
    return "unspecified"


_PRICE_WORDS = re.compile(r"стоит|стоят|цена|цену|стоимост|итого|всего|получится|выйдет|за м|за кв|за лист|за шт|по цене|тариф")


def _blank(match: re.Match) -> str:
    return " " * len(match.group(0))


def extract_price_mentions(manager_text: str, product: Product | None) -> list[_Mention]:
    """All money values in the reply: with a currency marker AND bare numbers in a price context.

    Both kinds are merged (non-overlapping, in text order) so a correct total cannot hide a
    wrong rate written without «тг». Sizes, thickness, codes, quantities and % are not prices.
    """
    # «м²» → «кв м» before normalization: NFKC turns ² into 2 and «м² × 8 000» would look like a size «2x8».
    prepared = re.sub(r"м\s?[²2](?![\d])", "кв м", manager_text)
    text = _strip_product_name(normalize(prepared), product)
    mentions: list[_Mention] = []
    spans: list[tuple[int, int]] = []
    for match in _MONEY.finditer(text):
        whole = re.sub(r"[ \u00a0\u202f]", "", match.group(1))
        amount = Decimal(whole + ("." + match.group(2) if match.group(2) else ""))
        clause = _clause(text, match.start(), match.end())
        mentions.append(_Mention(amount, match.group(0).strip(), _meaning(clause), match.start(), clause))
        spans.append(match.span())
    strict = bool(mentions)  # with currency-marked prices present, bare numbers need a price word nearby
    cleaned = re.sub(r"\d+(?:[.,]\d+)?\s*x\s*\d+(?:[.,]\d+)?(?:\s*x\s*\d+)?", _blank, text)  # keeps offsets
    for match in _BARE_NUMBER.finditer(cleaned):
        start, end = match.span()
        if any(s <= start < e or s < end <= e for s, e in spans):
            continue
        clause_start = max(cleaned.rfind(sep, 0, start) for sep in (",", ";", ".", "!", "?", "\n", "(")) + 1
        context_before = cleaned[max(clause_start, start - 30) : start]  # same clause only: «артикул 100» is no price
        if strict:
            if not _PRICE_WORDS.search(context_before):
                continue
        elif not (_PRICE_WORDS.search(context_before) or re.search(r"[:—]\s*$|-\s*$", context_before)):
            continue
        whole = re.sub(r"[ \u00a0\u202f]", "", match.group(1))
        amount = Decimal(whole + ("." + match.group(2) if match.group(2) else ""))
        clause = _clause(cleaned, start, end)
        mentions.append(_Mention(amount, match.group(0).strip(), _meaning(clause), start, clause))
    mentions.sort(key=lambda m: m.start)
    return mentions


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= TOLERANCE


@dataclass
class _Refs:
    values: dict[str, Decimal | None]
    evidence: dict[str, Evidence]
    total_requested: bool
    client_basis: str
    bulk_context: bool


def _references(kb: KnowledgeBase, product: Product, client: str, manager: str) -> _Refs:
    """KB prices of the product plus the order total from the SAME PricingInput normalization the
    assistant uses (quantity, processing kind, explicitly stated edge sides)."""

    def ev(field_name: str | None) -> Evidence:
        return Evidence(source=kb.source, source_version=kb.version, record_id=product.product_id, field=field_name)

    values: dict[str, Decimal | None] = {}
    evidence: dict[str, Evidence] = {}
    for entry in product.prices:
        values[entry.price_type] = entry.amount
        evidence[entry.price_type] = ev(entry.source_field)
    formats = {product.attributes["sheet_format_mm"]} if "sheet_format_mm" in product.attributes else set()
    ex = extract(client, format_exclusions=formats)
    total_requested = False
    if ex.dimensions and not product.is_hardware:
        total_requested = True
        dims = ex.dimensions[0]
        request, edge_unknown = pricing_input_for(
            product,
            length_mm=dims.length_mm,
            width_mm=dims.width_mm,
            quantity=ex.quantity or 1,
            processing="none" if ex.processing_negated else ex.processing,
            edge_sides=ex.edge_sides,
            selected_sides=ex.selected_sides,
            price_basis="per_m2",
        )
        values["total"] = None if edge_unknown else calculate(kb, request).total
        evidence["total"] = Evidence(source="pricing", source_version=kb.version, record_id=product.product_id, field="total")
    elif product.is_hardware and ex.quantity:
        total_requested = True
        values["total"] = calculate(kb, PricingInput(product, quantity=ex.quantity, price_basis="unit")).total
        evidence["total"] = Evidence(source="pricing", source_version=kb.version, record_id=product.product_id, field="total")
    bulk_context = ex.tier_inquiry or bool(re.search(r"от\s+\d+\s*(?:шт|штук)|оптом", normalize(manager)))
    return _Refs(values, evidence, total_requested, ex.price_basis, bulk_context)


@dataclass
class _Evaluation:
    verdict: str  # OK | ERROR | UNRESOLVED
    correct: Decimal | None
    key: str | None
    evidence: list[Evidence]
    mentions: list[_Mention]
    reason_code: str | None = None


def bulk_price_scope(product: Product, client: str, claim: str) -> str:
    """Eligible order / explicitly conditional tariff / retail order / unknown.

    A catalogue number alone never proves its tariff applies. A threshold bound
    to the same claim is a conditional rate, independently of the current order.
    """
    entry = product.price("bulk_unit")
    threshold = entry.minimum_quantity if entry else None
    if not product.is_hardware or threshold is None:
        return "unknown"
    condition = re.compile(r"\b(?:от|не менее|при)\s*(\d+)\s*(?:шт|штук|единиц)")
    stated = [int(match.group(1)) for match in condition.finditer(normalize(claim))]
    if stated:
        return "conditional" if all(value >= threshold for value in stated) else "unsupported_condition"
    # The customer may explicitly be asking about that tariff, rather than
    # placing an order at their currently mentioned quantity.
    if any(int(match.group(1)) >= threshold for match in condition.finditer(normalize(client))):
        return "conditional"
    quantity = extract(client).quantity
    if quantity is None:
        return "unknown"
    return "eligible" if quantity >= threshold else "retail"


def _candidates_for(mention: _Mention, refs: _Refs, product: Product) -> tuple[list[str], str | None]:
    """Reference keys a mention may legitimately mean, and the key that defines its correction."""
    values = refs.values
    if mention.meaning in {"per_m2", "per_sheet", "retail_unit", "bulk_unit", "total"}:
        return [mention.meaning], mention.meaning
    if product.is_hardware:
        keys = ["retail_unit"] + (["bulk_unit"] if refs.bulk_context else []) + (["total"] if refs.total_requested else [])
        return keys, "total" if refs.total_requested else "retail_unit"
    if refs.total_requested:
        return ["total", "per_m2"], "total"
    keys = ["per_sheet", "per_m2"] if refs.client_basis == "per_sheet" else ["per_m2", "per_sheet"]
    correction = next((k for k in keys if values.get(k) is not None), None)
    return keys, correction


def _evaluate(kb: KnowledgeBase, product: Product, client: str, manager: str) -> _Evaluation:
    refs = _references(kb, product, client, manager)
    mentions = extract_price_mentions(manager, product)
    evidence: list[Evidence] = []
    error: tuple[Decimal, str] | None = None
    error_reason = None
    unresolved = False
    unresolved_reason = None
    for mention in mentions:
        keys, correction_key = _candidates_for(mention, refs, product)
        if "bulk_unit" in keys:
            scope = bulk_price_scope(product, client, mention.clause)
            if mention.meaning == "bulk_unit" and scope == "retail":
                retail = refs.values.get("retail_unit")
                if retail is not None:
                    evidence.append(refs.evidence["retail_unit"])
                    if error is None:
                        error, error_reason = (retail, "retail_unit"), "bulk_threshold_not_met"
                else:
                    unresolved, unresolved_reason = True, "bulk_threshold_unconfirmed"
                continue
            if mention.meaning == "bulk_unit" and scope in {"unknown", "unsupported_condition"}:
                unresolved, unresolved_reason = True, ("bulk_condition_not_supported" if scope == "unsupported_condition"
                                                       else "bulk_threshold_unconfirmed")
                continue
            if scope not in {"eligible", "conditional"}:
                keys = [key for key in keys if key != "bulk_unit"]
        known = [(k, refs.values[k]) for k in keys if refs.values.get(k) is not None]
        hit = next((k for k, value in known if _close(mention.amount, value)), None)
        if hit is not None:
            evidence.append(refs.evidence[hit])
            continue
        correct = refs.values.get(correction_key) if correction_key else None
        if correct is None:
            unresolved = True  # the meaning's reference is unknown in KB/Pricing: no correction exists
            continue
        evidence.append(refs.evidence[correction_key])
        if error is None:
            error = (correct, correction_key)
    if error is not None:
        return _Evaluation("ERROR", error[0], error[1], evidence, mentions, error_reason)
    if unresolved:
        return _Evaluation("UNRESOLVED", None, None, evidence, mentions, unresolved_reason)
    key = None
    if mentions:
        for k in ("retail_unit", "per_m2", "total", "per_sheet", "bulk_unit"):
            if refs.values.get(k) is not None and _close(mentions[0].amount, refs.values[k]):
                key = k
                break
    return _Evaluation("OK", None, key, evidence, mentions)


def _views(mentions: list[_Mention]) -> list[PriceMention]:
    return [PriceMention(raw=m.raw, amount_tg=money_string(m.amount), meaning=m.meaning) for m in mentions]


def _from_evaluation(dialog_id: str, product: Product, evaluation: _Evaluation, reason: str, digest: str) -> DialogVerdict:
    base = dict(id=dialog_id, mentions=_views(evaluation.mentions), input_sha256=digest, catalog_product_id=product.product_id)
    if not evaluation.mentions:
        return DialogVerdict(verdict="OK", evidence=[], reason_code="no_price_claim",
                             explanation_ru="Менеджер не назвал цену; ложной цены нет.", **base)
    if evaluation.verdict == "ERROR":
        correct = money_string(evaluation.correct)
        return DialogVerdict(
            verdict="ERROR", correct=correct, evidence=evaluation.evidence, reference_tg=correct,
            reference_meaning=evaluation.key, reason_code=evaluation.reason_code or "price_mismatch",
            explanation_ru=(f"Оптовый порог не достигнут: применима розничная цена {correct} ₸ за шт."
                            if evaluation.reason_code == "bulk_threshold_not_met" else
                            f"Цена в ответе не совпадает с базой: правильно {correct} ₸ ({evaluation.key})."), **base,
        )
    if evaluation.verdict == "UNRESOLVED":
        return DialogVerdict(
            verdict="NEEDS_REVIEW", evidence=evaluation.evidence, reason_code=evaluation.reason_code or "price_not_in_kb",
            explanation_ru=("Не подтверждено количество или условие оптового порога; уточните применимость тарифа."
                            if evaluation.reason_code in {"bulk_threshold_unconfirmed", "bulk_condition_not_supported"} else
                            "Цены для этого смысла числа нет в базе; проверить может только менеджер."), **base,
        )
    return DialogVerdict(
        verdict="OK", evidence=evaluation.evidence, reference_tg=None, reference_meaning=evaluation.key,
        reason_code=reason, explanation_ru="Цена совпадает с базой знаний.", **base,
    )


def check_dialog(kb: KnowledgeBase, dialog_id: str, client: str, manager: str) -> DialogVerdict:
    digest = hashlib.sha256(f"{client}\x1f{manager}".encode("utf-8")).hexdigest()
    if extract(f"{client} {manager}").model_codes:
        return _model_code_verdict(kb, dialog_id, client, manager, digest)
    client_match = match_products(kb, client)
    if client_match.reason_code in UNSUPPORTED_IDENTIFIERS:
        return _needs_review(dialog_id, manager, digest, "explicit_unknown_product",
                             "Указанный артикул или бренд не подтвержден каталогом; нельзя подменять его ценой другой позиции.")
    if client_match.status == "exact":
        product = client_match.product
        return _from_evaluation(dialog_id, product, _evaluate(kb, product, client, manager), "price_matches_kb", digest)
    manager_match = match_products(kb, manager)
    if client_match.status == "ambiguous":
        ids = {c.product.product_id for c in client_match.candidates}
        if manager_match.status == "exact" and manager_match.product.product_id in ids:
            product = manager_match.product
            return _from_evaluation(dialog_id, product, _evaluate(kb, product, client, manager), "manager_refined_client_ambiguity", digest)
        if manager_match.status == "exact":
            return _needs_review(dialog_id, manager, digest, "manager_product_outside_client_candidates",
                                 "Менеджер назвал позицию, не подходящую под вопрос клиента.")
        return _ambiguous_verdict(kb, dialog_id, client, manager, [c.product for c in client_match.candidates], digest)
    if manager_match.status == "exact":
        product = manager_match.product
        return _from_evaluation(dialog_id, product, _evaluate(kb, product, client, manager), "manager_named_product", digest)
    mentions = extract_price_mentions(manager, None)
    if not mentions:
        return DialogVerdict(id=dialog_id, verdict="OK", evidence=[], mentions=[], input_sha256=digest,
                             reason_code="no_price_claim", explanation_ru="В ответе нет цены, проверять нечего.")
    return _needs_review(dialog_id, manager, digest, f"client_{client_match.status}",
                         "Не удалось однозначно определить товар по базе знаний.")


def _needs_review(dialog_id: str, manager: str, digest: str, reason: str, explanation: str, **extra) -> DialogVerdict:
    return DialogVerdict(
        id=dialog_id, verdict="NEEDS_REVIEW", correct=None, evidence=extra.pop("evidence", []),
        mentions=_views(extract_price_mentions(manager, None)), input_sha256=digest, reason_code=reason,
        explanation_ru=explanation, **extra,
    )


def _ambiguous_verdict(kb, dialog_id, client, manager, candidates: list[Product], digest) -> DialogVerdict:
    """Evaluate every interpretation. OK if the price fits one; ERROR only if all interpretations
    prove the same correction; otherwise NEEDS_REVIEW with correct=None (never chosen by rank)."""
    evaluations = [(product, _evaluate(kb, product, client, manager)) for product in candidates]
    if all(not e.mentions for _, e in evaluations):
        return DialogVerdict(id=dialog_id, verdict="OK", evidence=[], mentions=[], input_sha256=digest,
                             reason_code="no_price_claim", explanation_ru="Менеджер не назвал цену; ложной цены нет.")
    fitting = [(p, e) for p, e in evaluations if e.verdict == "OK" and e.mentions]
    if fitting:
        product, evaluation = fitting[0] if len(fitting) == 1 else (None, fitting[0][1])
        names = ", ".join(p.name for p, _ in fitting)
        return DialogVerdict(
            id=dialog_id, verdict="OK", evidence=[ev for _, e in fitting for ev in e.evidence][:10],
            mentions=_views(evaluation.mentions), input_sha256=digest,
            catalog_product_id=product.product_id if product else None,
            reason_code="price_matches_candidate_interpretation",
            explanation_ru=f"Цена совпадает с базой для позиции: {names}.",
        )
    errors = [(p, e) for p, e in evaluations if e.verdict == "ERROR"]
    corrections = {e.correct for _, e in errors}
    if len(errors) == len(evaluations) and len(corrections) == 1:
        correct = money_string(corrections.pop())
        return DialogVerdict(
            id=dialog_id, verdict="ERROR", correct=correct, evidence=[ev for _, e in errors for ev in e.evidence][:10],
            mentions=_views(errors[0][1].mentions), input_sha256=digest, reference_tg=correct,
            reference_meaning=errors[0][1].key, reason_code="price_mismatch_all_interpretations",
            explanation_ru=f"Для всех подходящих позиций база дает одну цену {correct} ₸; в ответе другая.",
        )
    options = "; ".join(
        f"{p.name}: {money_string(e.correct) + ' ₸' if e.correct is not None else 'цена неизвестна'}" for p, e in evaluations
    )
    return _needs_review(
        dialog_id, manager, digest, "ambiguous_product_correction_not_unique",
        f"Цена не совпадает ни с одной трактовкой вопроса, а исправления различаются ({options}); нужен выбор товара.",
        evidence=[ev for _, e in evaluations for ev in e.evidence][:10],
    )


def _model_code_verdict(kb, dialog_id, client, manager, digest) -> DialogVerdict:
    codes = extract(f"{client} {manager}").model_codes
    rng = kb.model_range
    missing = {code for code, _ in kb.missing_models}
    mentions = extract_price_mentions(manager, None)
    if codes and rng and all(
        code.startswith(rng[0]) and rng[1] <= int(re.sub(r"\D", "", code)) <= rng[2] and code not in missing for code in codes
    ):
        return DialogVerdict(
            id=dialog_id, verdict="OK", evidence=[Evidence(source=kb.source, source_version=kb.version, record_id=rng[3], field="правило")],
            mentions=_views(mentions), input_sha256=digest, reason_code="price_set_by_manager_per_kb_rule",
            explanation_ru="По базе цены этих моделей рассчитывает менеджер; противоречия базе нет.",
        )
    if not mentions:
        return DialogVerdict(id=dialog_id, verdict="OK", evidence=[], mentions=[], input_sha256=digest,
                             reason_code="no_price_claim", explanation_ru="В ответе нет цены, проверять нечего.")
    return _needs_review(dialog_id, manager, digest, "model_not_in_catalog", "Модели нет в каталоге; цену проверяет менеджер.")
