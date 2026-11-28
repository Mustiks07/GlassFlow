"""Domain tools for the AI dispatcher (TZ §15).

Each tool has a strict argument model (extra fields forbidden, bounded sizes) and a bounded,
typed result. Model tool calls are untrusted: unknown tools, malformed JSON and invalid
arguments are rejected before anything runs. Effects are limited to reads, quote drafts and
reminder/scenario *drafts*; there is no SQL, shell, HTTP, messaging, payment, reservation or
confirmation tool. Cross-domain work goes through injected ports.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from glassflow.contracts.common import Dimensions
from glassflow.contracts.crm import RankRequest, ReminderRequest
from glassflow.contracts.cutting import FindRequest

from ..catalog.kb import KnowledgeBase, Product
from ..catalog.mapping import MappingDecision
from ..catalog.matching import match_products
from ..ports_consumed import CrmPort, InventoryPort, ScenarioPort, ServiceUnavailable
from ..pricing import PricingInputError, calculate, money_str, pricing_input_for
from .facts import FactSet
from .local import recommend_accessories
from .verifier import verify_answer

MAX_RESULT_CHARS = 6000


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=False)


class SearchCatalogArgs(_Args):
    query: str = Field(min_length=1, max_length=200)
    kind: Literal["material", "hardware", "any"] = "any"


class GetRulesArgs(_Args):
    topic: Literal["installation", "payment", "delivery", "discount", "edge_processing", "mirror_models", "pricing_source", "all"]


class CalculateQuoteArgs(_Args):
    catalog_product_id: str = Field(min_length=1, max_length=128)
    length_mm: int | None = Field(default=None, gt=0, le=20000)
    width_mm: int | None = Field(default=None, gt=0, le=20000)
    quantity: int | None = Field(default=None, gt=0, le=100000)
    processing: Literal["none", "euro_edge", "facet", "sandblast"] = "none"
    edge_sides: Literal["all", "long", "short", "top", "bottom", "left", "right", "unknown"] = "unknown"
    price_basis: Literal["auto", "per_m2", "per_sheet", "unit"] = "auto"


class ResolveMaterialArgs(_Args):
    catalog_product_id: str = Field(min_length=1, max_length=128)


class FindRemnantsArgs(_Args):
    catalog_product_id: str = Field(min_length=1, max_length=128)
    length_mm: int = Field(gt=0, le=20000)
    width_mm: int = Field(gt=0, le=20000)
    premium: bool = False


class RecommendAccessoriesArgs(_Args):
    purpose: str = Field(min_length=1, max_length=200)


class RankFollowupsArgs(_Args):
    policy: Literal["reference", "validated_model"] = "reference"


class DraftReminderArgs(_Args):
    recipient_client_id: str = Field(min_length=1, max_length=128)
    source_app_ids: list[str] = Field(min_length=1, max_length=25)
    subject_type: Literal["interest", "quote_example", "specific_remnant"]
    subject_ref: str | None = Field(default=None, max_length=128)
    owner: str = Field(min_length=1, max_length=64)


class CompareScenarioArgs(_Args):
    base_plan_id: str = Field(min_length=1, max_length=128)
    change: dict[str, str | int] = Field(max_length=10)


class VerifyAnswerArgs(_Args):
    answer_ru: str = Field(min_length=1, max_length=1500)


class SubmitAnswerArgs(_Args):
    answer_ru: str = Field(min_length=1, max_length=1200)
    clarification: str | None = Field(default=None, max_length=400)
    needs_manager: bool = False


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


_STR = {"type": "string"}
_INT = {"type": "integer", "minimum": 1}


@dataclass
class ToolContext:
    kb: KnowledgeBase
    mappings: dict[str, MappingDecision]
    dataset_id: str
    inventory: InventoryPort | None = None
    crm: CrmPort | None = None
    scenario: ScenarioPort | None = None
    user_text: str = ""
    facts: FactSet = field(default_factory=FactSet)
    remnant_checked: bool = False
    products_seen: set[str] = field(default_factory=set)
    last_quote: Any = None


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    args_model: type[_Args]
    effect: str  # read | draft_quote | draft_task | job | none
    run: Callable[[ToolContext, Any], dict[str, Any]]


def _product_view(product: Product) -> dict[str, Any]:
    return {
        "catalog_product_id": product.product_id,
        "name": product.name,
        "kind": product.kind,
        "prices": [
            {"price_type": p.price_type, "amount_tg": money_str(p.amount) if p.amount is not None else None, "min_quantity": p.minimum_quantity}
            for p in product.prices
        ],
    }


def _remember_prices(ctx: ToolContext, product: Product) -> None:
    ctx.products_seen.add(product.product_id)
    for number in re.findall(r"\d+", product.name):
        ctx.facts.add("name", int(number), None, f"kb:{ctx.kb.version}:{product.product_id}:название")
    for price in product.prices:
        if price.amount is not None:
            ctx.facts.add("price", price.amount, price.unit, f"kb:{ctx.kb.version}:{product.product_id}:{price.source_field}")
            tier = f"при количестве от {price.minimum_quantity} шт." if price.minimum_quantity else price.price_type
            ctx.facts.claim(f"{product.name}: {money_str(price.amount)} {price.unit}, {tier}.",
                            source_ref=f"renderer:kb:{ctx.kb.version}:{product.product_id}:{price.source_field}")
        if price.minimum_quantity:
            ctx.facts.add("threshold", price.minimum_quantity, "шт", f"kb:{ctx.kb.version}:{product.product_id}:{price.source_field}")


def _search(ctx: ToolContext, args: SearchCatalogArgs) -> dict[str, Any]:
    kinds = None if args.kind == "any" else {args.kind}
    result = match_products(ctx.kb, args.query, kinds=kinds)
    for candidate in result.candidates[:6]:
        _remember_prices(ctx, candidate.product)
    return {"status": result.status, "candidates": [_product_view(c.product) for c in result.candidates[:6]]}


def _rules(ctx: ToolContext, args: GetRulesArgs) -> dict[str, Any]:
    rules = ctx.kb.rules if args.topic == "all" else ctx.kb.rules_for(args.topic)
    for rule in rules:
        ctx.facts.add("rule", rule.rule_id, None, f"kb:{ctx.kb.version}:{rule.rule_id}")
    if args.topic in {"edge_processing", "all"}:
        for rate in ctx.kb.edge_rates:
            ctx.facts.add("price", rate.amount_per_m, "₸/м", f"kb:{ctx.kb.version}:{rate.rule_id}")
            ctx.facts.add("measure", rate.thickness_mm, "мм", f"kb:{ctx.kb.version}:{rate.rule_id}")
    return {"rules": [{"rule_id": r.rule_id, "text": r.text} for r in rules]}


def _product_or_error(ctx: ToolContext, product_id: str) -> Product:
    product = ctx.kb.product(product_id)
    if product is None:
        raise ToolRejected("unknown_catalog_product_id", "Нет такой позиции в текущей версии KB.")
    return product


def _quote(ctx: ToolContext, args: CalculateQuoteArgs) -> dict[str, Any]:
    product = _product_or_error(ctx, args.catalog_product_id)
    if (args.length_mm is None) != (args.width_mm is None):
        raise ToolRejected("dimensions_incomplete", "Нужны обе стороны детали.")
    edge_sides, selected = None, ()
    if args.edge_sides == "all":
        edge_sides = "all"
    elif args.edge_sides in {"long", "short"}:
        edge_sides, selected = "selected", (args.edge_sides,)
    elif args.edge_sides in {"top", "bottom", "left", "right"}:
        edge_sides, selected = "selected", (args.edge_sides,)
    quantity = args.quantity if args.quantity is not None else (1 if args.length_mm else None)
    request, _ = pricing_input_for(
        product, length_mm=args.length_mm, width_mm=args.width_mm, quantity=quantity, processing=args.processing,
        edge_sides=edge_sides, selected_sides=selected, price_basis=args.price_basis,
    )
    try:
        result = calculate(ctx.kb, request)
    except PricingInputError as exc:
        raise ToolRejected(f"invalid_{exc.field_name}", exc.message_ru) from None
    _remember_prices(ctx, product)
    for line in result.lines:
        ctx.facts.add("line", line.amount, "₸", f"pricing:{line.component}")
        ctx.facts.add("price", line.unit_price, line.unit, f"pricing:{line.component}:rate")
        if line.measure_per_unit is not None:
            ctx.facts.add("measure", line.measure_per_unit, line.unit, f"pricing:{line.component}:measure")
    if result.total is not None:
        ctx.facts.add("total", result.total, "₸", "pricing:total")
        ctx.facts.add_quote([line.amount for line in result.lines], result.total)
    if result.known_subtotal is not None:
        ctx.facts.add("total", result.known_subtotal, "₸", "pricing:known_subtotal")
    if args.length_mm:
        ctx.facts.add("dimension", args.length_mm, "мм", "input")
        ctx.facts.add("dimension", args.width_mm, "мм", "input")
    if quantity:
        ctx.facts.add("quantity", quantity, "шт", "input")
    ctx.last_quote = result
    details = "; ".join(f"{line.label}: {money_str(line.amount)} ₸" for line in result.lines)
    dimensions = f"{args.length_mm}×{args.width_mm} мм, " if args.length_mm else ""
    total = f"итого {money_str(result.total)} ₸" if result.total is not None else "общий итог неизвестен"
    ctx.facts.claim(f"{product.name}, {dimensions}количество {quantity if quantity is not None else 'не уточнено'}: "
                    f"{details}; {total}; предварительно, условия подтверждает менеджер.", "quote")
    return {
        "catalog_product_id": product.product_id,
        "product_name": product.name,
        "lines": [
            {"component": line.component, "label": line.label, "amount_tg": money_str(line.amount), "formula": line.formula}
            for line in result.lines
        ],
        "total_tg": money_str(result.total),
        "known_subtotal_tg": money_str(result.known_subtotal),
        "unknown": [{"component": u.component, "reason": u.reason_code, "message_ru": u.message_ru} for u in result.unknowns],
        "preliminary": True,
        "assumptions": result.assumptions + (["quantity defaulted to 1"] if args.quantity is None and args.length_mm else []),
    }


def _resolve(ctx: ToolContext, args: ResolveMaterialArgs) -> dict[str, Any]:
    _product_or_error(ctx, args.catalog_product_id)
    mapping = ctx.mappings.get(args.catalog_product_id)
    if mapping is None:
        return {"status": "unmapped", "material_id": None}
    return {
        "status": mapping.status,
        "material_id": mapping.material_id,
        "candidate_material_ids": list(mapping.candidate_material_ids),
        "basis": mapping.basis,
        "version": mapping.version,
    }


def _remnants(ctx: ToolContext, args: FindRemnantsArgs) -> dict[str, Any]:
    _product_or_error(ctx, args.catalog_product_id)
    mapping = ctx.mappings.get(args.catalog_product_id)
    if mapping is None or mapping.status != "confirmed" or not mapping.material_id:
        return {"status": "mapping_required", "candidates": [], "message_ru": "Складское соответствие не подтверждено."}
    if ctx.inventory is None:
        return {
            "status": "service_unavailable",
            "candidates": [],
            "message_ru": "Проверка склада сейчас недоступна: о наличии или отсутствии остатков ничего утверждать нельзя.",
        }
    try:
        found = ctx.inventory.find_candidates(
            FindRequest(
                dataset_id=ctx.dataset_id,
                material_id=mapping.material_id,
                dimensions=Dimensions(length_mm=args.length_mm, width_mm=args.width_mm),
                premium=args.premium,
            )
        )
    except ServiceUnavailable:
        return {
            "status": "service_unavailable",
            "candidates": [],
            "message_ru": "Проверка склада сейчас недоступна: о наличии или отсутствии остатков ничего утверждать нельзя.",
        }
    ctx.remnant_checked = True
    for candidate in found.candidates[:5]:
        ctx.facts.add("remnant", candidate.remnant_id, None, f"inventory:{candidate.remnant_id}:v{candidate.remnant_version}")
        ctx.facts.add("measure", candidate.x_mm, "мм", "inventory:x")
        ctx.facts.add("measure", candidate.y_mm, "мм", "inventory:y")
    return {
        "status": "checked",
        "note": "Только просмотр: резерв создается менеджером после подтверждения и повторной проверки версии.",
        "candidates": [c.model_dump() for c in found.candidates[:5]],
        "reason_codes": found.reason_codes,
    }


def _accessories(ctx: ToolContext, args: RecommendAccessoriesArgs) -> dict[str, Any]:
    items = recommend_accessories(ctx.kb, args.purpose)[:5]
    for product in items:
        _remember_prices(ctx, product)
    return {
        "items": [_product_view(p) for p in items],
        "compatibility": "Совместимость база знаний не подтверждает; ее проверяет менеджер.",
    }


def _rank(ctx: ToolContext, args: RankFollowupsArgs) -> dict[str, Any]:
    if ctx.crm is None:
        return {"status": "service_unavailable"}
    ranking = ctx.crm.rank(RankRequest(dataset_id=ctx.dataset_id, policy=args.policy))
    return {
        "status": "ok",
        "policy": ranking.policy,
        "unique_client_count": ranking.unique_client_count,
        "rows": [r.model_dump() for r in ranking.rows[:25]],
        "note": "Совпадение по группе товара — возможная релевантность, не доказанная потребность.",
    }


def _reminder(ctx: ToolContext, args: DraftReminderArgs) -> dict[str, Any]:
    if ctx.crm is None:
        return {"status": "service_unavailable"}
    reminder = ctx.crm.draft_reminder(
        ReminderRequest(
            dataset_id=ctx.dataset_id,
            recipient_client_id=args.recipient_client_id,
            source_app_ids=args.source_app_ids,
            subject_type=args.subject_type,
            subject_ref=args.subject_ref,
            owner=args.owner,
        )
    )
    return {"status": "draft", "reminder": reminder.model_dump(), "note": "Черновик; подтверждение только в интерфейсе."}


def _scenario(ctx: ToolContext, args: CompareScenarioArgs) -> dict[str, Any]:
    if ctx.scenario is None:
        return {"status": "service_unavailable"}
    return {"status": "submitted", "result": ctx.scenario.compare(ctx.dataset_id, args.base_plan_id, dict(args.change))}


def _verify(ctx: ToolContext, args: VerifyAnswerArgs) -> dict[str, Any]:
    result = verify_answer(args.answer_ru, ctx.facts, ctx.user_text, remnant_checked=ctx.remnant_checked)
    payload: dict[str, Any] = {"status": result.status, "unsupported": result.unsupported}
    if any(item.startswith("claim:incomplete_total") for item in result.unsupported):
        payload["hint_ru"] = "Назовите итог расчета calculate_quote (total_tg) вместе с позициями."
    return payload


def _submit(ctx: ToolContext, args: SubmitAnswerArgs) -> dict[str, Any]:
    return {"status": "received"}


TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in [
        Tool("search_catalog", "Найти позиции каталога KSM по тексту; возвращает id, названия и цены из KB.",
             _schema({"query": _STR, "kind": {"type": "string", "enum": ["material", "hardware", "any"]}}, ["query"]),
             SearchCatalogArgs, "read", _search),
        Tool("get_rules", "Правила компании из KB по теме (монтаж, оплата, доставка, скидки, кромка, модели AB).",
             _schema({"topic": {"type": "string", "enum": list(GetRulesArgs.model_fields["topic"].annotation.__args__)}}, ["topic"]),
             GetRulesArgs, "read", _rules),
        Tool("calculate_quote", "Точный предварительный расчет позиции по размерам (мм), количеству и обработке.",
             _schema({
                 "catalog_product_id": _STR, "length_mm": _INT, "width_mm": _INT, "quantity": _INT,
                 "processing": {"type": "string", "enum": ["none", "euro_edge", "facet", "sandblast"]},
                 "edge_sides": {"type": "string", "enum": ["all", "long", "short", "top", "bottom", "left", "right", "unknown"]},
                 "price_basis": {"type": "string", "enum": ["auto", "per_m2", "per_sheet", "unit"]},
             }, ["catalog_product_id"]),
             CalculateQuoteArgs, "draft_quote", _quote),
        Tool("resolve_material", "Подтвержденное складское соответствие позиции каталога (или unmapped/ambiguous).",
             _schema({"catalog_product_id": _STR}, ["catalog_product_id"]), ResolveMaterialArgs, "read", _resolve),
        Tool("find_remnants", "Свободные подходящие остатки для детали; только просмотр, без резерва.",
             _schema({"catalog_product_id": _STR, "length_mm": _INT, "width_mm": _INT, "premium": {"type": "boolean"}},
                     ["catalog_product_id", "length_mm", "width_mm"]), FindRemnantsArgs, "read", _remnants),
        Tool("recommend_accessories", "Сопутствующие позиции каталога по назначению; без гарантий совместимости.",
             _schema({"purpose": _STR}, ["purpose"]), RecommendAccessoriesArgs, "read", _accessories),
        Tool("rank_followups", "CRM: приоритетные заявки для повторного контакта (не меняет заказчика).",
             _schema({"policy": {"type": "string", "enum": ["reference", "validated_model"]}}, []), RankFollowupsArgs, "read", _rank),
        Tool("draft_reminder", "CRM: черновик локального напоминания; подтверждение только менеджером в интерфейсе.",
             _schema({"recipient_client_id": _STR, "source_app_ids": {"type": "array", "items": _STR},
                      "subject_type": {"type": "string", "enum": ["interest", "quote_example", "specific_remnant"]},
                      "subject_ref": _STR, "owner": _STR}, ["recipient_client_id", "source_app_ids", "subject_type", "owner"]),
             DraftReminderArgs, "draft_task", _reminder),
        Tool("compare_scenario", "Запустить сравнение сценария раскроя; сценарий не применяется.",
             _schema({"base_plan_id": _STR, "change": {"type": "object"}}, ["base_plan_id", "change"]),
             CompareScenarioArgs, "job", _scenario),
        Tool("verify_answer", "Проверить черновик ответа на неподтвержденные цены, сроки, скидки и обещания.",
             _schema({"answer_ru": _STR}, ["answer_ru"]), VerifyAnswerArgs, "read", _verify),
        Tool("submit_answer", "Финальный короткий ответ клиенту (2–4 предложения) и уточняющий вопрос при необходимости.",
             _schema({"answer_ru": _STR, "clarification": _STR, "needs_manager": {"type": "boolean"}}, ["answer_ru"]),
             SubmitAnswerArgs, "none", _submit),
    ]
}
ASSISTANT_TOOLSET = [
    "search_catalog", "get_rules", "calculate_quote", "resolve_material", "find_remnants",
    "recommend_accessories", "rank_followups", "draft_reminder", "compare_scenario", "verify_answer", "submit_answer",
]


class ToolRejected(Exception):
    def __init__(self, code: str, message_ru: str):
        super().__init__(message_ru)
        self.code = code
        self.message_ru = message_ru


@dataclass
class ToolExecution:
    name: str
    status: str  # ok | rejected | error | unavailable
    arguments: dict[str, Any]
    result: dict[str, Any]
    error_code: str | None = None

    def result_json(self) -> str:
        text = json.dumps(self.result, ensure_ascii=False)
        if len(text) > MAX_RESULT_CHARS:
            text = json.dumps({"status": "truncated", "detail": text[: MAX_RESULT_CHARS - 100]}, ensure_ascii=False)
        return text


def execute_tool(ctx: ToolContext, name: str, raw_arguments: str | dict | None, allowed: list[str] | None = None) -> ToolExecution:
    allowed = allowed or ASSISTANT_TOOLSET
    if name not in TOOLS or name not in allowed:
        return ToolExecution(name, "rejected", {}, {"error": "tool_not_allowed"}, "TOOL_NOT_ALLOWED")
    tool = TOOLS[name]
    if isinstance(raw_arguments, dict):
        data = raw_arguments
    else:
        try:
            data = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError:
            return ToolExecution(name, "rejected", {}, {"error": "malformed_json"}, "MALFORMED_TOOL_JSON")
    if not isinstance(data, dict):
        return ToolExecution(name, "rejected", {}, {"error": "arguments_must_be_object"}, "MALFORMED_TOOL_JSON")
    try:
        args = tool.args_model.model_validate(data)
    except ValidationError as exc:
        errors = [f"{'.'.join(map(str, e['loc']))}: {e['type']}" for e in exc.errors()[:5]]
        return ToolExecution(name, "rejected", {}, {"error": "invalid_arguments", "details": errors}, "INVALID_TOOL_ARGUMENTS")
    safe_args = args.model_dump()
    try:
        result = tool.run(ctx, args)
    except ToolRejected as exc:
        return ToolExecution(name, "rejected", safe_args, {"error": exc.code, "message_ru": exc.message_ru}, exc.code)
    except ServiceUnavailable as exc:
        return ToolExecution(name, "unavailable", safe_args, {"status": "service_unavailable", "service": exc.service}, "SERVICE_UNAVAILABLE")
    status = "unavailable" if result.get("status") == "service_unavailable" else "ok"
    result["commercial_references"] = {f"[[{k}]]": v for k, v in ctx.facts.commercial_claims.items()}
    return ToolExecution(name, status, safe_args, result)
