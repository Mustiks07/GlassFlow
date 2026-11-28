"""Catalog, pricing, assistant and dialog-quality DTOs (owner: Claude 3).

Money is always a decimal string; geometry is integer millimetres. Unknown values are null,
never zero. All fields added after the foundation snapshot are optional/defaulted, so the
foundation request shapes remain valid.
"""

from typing import Literal

from pydantic import Field, model_validator

from .common import DTO, DatasetRequest, Dimensions, Evidence, Identifier, MoneyString

MappingStatus = Literal["confirmed", "proposed", "ambiguous", "unmapped"]


class CatalogPrice(DTO):
    price_type: Literal["per_m2", "per_sheet", "retail_unit", "bulk_unit", "per_m"]
    amount_tg: MoneyString | None
    minimum_quantity: int | None = None
    unit: str | None = None
    source_field: str | None = None


class MaterialMapping(DTO):
    """Explicit catalog product → warehouse material relation. Never inferred silently."""

    dataset_id: Identifier
    catalog_product_id: Identifier
    material_id: str | None
    status: MappingStatus
    basis: str
    candidate_material_ids: list[str] = Field(default_factory=list)
    confirmed_by: str | None = None
    version: int = 0
    kb_version: str
    materials_version: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class CatalogProduct(DTO):
    catalog_product_id: Identifier
    name: str
    category: str
    prices: list[CatalogPrice]
    evidence: list[Evidence]
    kind: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    unknown_fields: dict[str, str] = Field(default_factory=dict)
    kb_version: str | None = None
    mapping: MaterialMapping | None = None


class CatalogRule(DTO):
    rule_id: str
    text: str
    topics: list[str]
    kb_version: str


class CatalogSearchResult(DTO):
    query: str
    status: Literal["exact", "best", "ambiguous", "not_found"]
    candidates: list[CatalogProduct]
    clarification: str | None = None
    kb_version: str


class PriceVersion(DTO):
    kb_version: str
    sha256: str
    source: str
    product_count: int
    current: bool


class MappingConfirmRequest(DatasetRequest):
    material_id: str | None
    status: Literal["confirmed", "unmapped"] = "confirmed"
    expected_version: int = Field(ge=0)
    confirmed_by: str = Field(min_length=1, max_length=128)
    basis: str = Field(default="manager_confirmation", max_length=500)


class Processing(DTO):
    kind: Literal["none", "euro_edge", "facet", "sandblast"] = "none"
    sides: Literal["all", "selected"] = "all"
    selected_sides: list[Literal["left", "right", "top", "bottom"]] = Field(default_factory=list)


class QuoteRequest(DatasetRequest):
    catalog_product_id: Identifier
    dimensions: Dimensions | None = None
    quantity: int | None = Field(default=1, gt=0, strict=True)
    processing: Processing = Field(default_factory=Processing)
    kb_version: str
    customer_id: str | None = None
    price_basis: Literal["auto", "per_m2", "per_sheet", "unit"] = "auto"
    inventory_mode: Literal["none", "free_whole_remnants", "replan"] = "none"
    premium: bool = False
    assumptions: list[str] = Field(default_factory=list, max_length=20)


class QuoteLine(DTO):
    label: str
    amount_tg: MoneyString
    evidence: list[Evidence]
    component: Literal["glass", "sheet", "edge", "hardware"] | None = None
    quantity: int | None = None
    unit_price_tg: MoneyString | None = None
    unit: str | None = None
    measure_per_unit: str | None = None
    exact_amount_tg: str | None = None
    formula: str | None = None


class UnknownComponent(DTO):
    component: str
    reason_code: str
    message_ru: str
    evidence: list[Evidence] = Field(default_factory=list)


class RemnantCandidateRef(DTO):
    remnant_id: str
    remnant_version: int
    x_mm: int
    y_mm: int
    rot: Literal[0, 1]
    location_raw: str


class QuoteLineDiff(DTO):
    component: str
    before_tg: MoneyString | None
    after_tg: MoneyString | None


class QuoteDiff(DTO):
    from_revision: int
    to_revision: int
    changed_fields: list[str]
    lines: list[QuoteLineDiff]
    total_before_tg: MoneyString | None
    total_after_tg: MoneyString | None


class Quote(DatasetRequest):
    origin: Literal["explicit_request", "assistant_deterministic", "assistant_model"] = "explicit_request"
    origin_conversation_id: str | None = None
    origin_turn_index: int | None = None
    quote_id: Identifier
    revision: int
    status: Literal["calculated", "needs_review", "ready", "confirmed", "superseded", "cancelled"]
    components: list[QuoteLine]
    total_tg: MoneyString | None
    preliminary: bool = True
    clarification: str | None = None
    material_mapping_status: MappingStatus
    material_id: str | None = None
    catalog_product_id: str | None = None
    product_name: str | None = None
    kb_version: str | None = None
    customer_id: str | None = None
    dimensions: Dimensions | None = None
    quantity: int | None = None
    processing: Processing | None = None
    price_basis: str | None = None
    confirmed_parameters: dict[str, str] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    unknown_components: list[UnknownComponent] = Field(default_factory=list)
    known_subtotal_tg: MoneyString | None = None
    rounding_policy: str = "ROUND_HALF_UP to 0.01 per line; total equals the sum of displayed lines"
    source_versions: dict[str, str] = Field(default_factory=dict)
    inventory_status: Literal[
        "not_requested", "checked", "mapping_required", "unavailable", "service_unavailable"
    ] = "not_requested"
    candidate_refs: list[RemnantCandidateRef] = Field(default_factory=list)
    inventory_reason_codes: list[str] = Field(default_factory=list)
    stale: bool = False
    created_at: str | None = None
    confirmed_at: str | None = None
    confirmed_by: str | None = None
    diff: QuoteDiff | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class QuoteChanges(DTO):
    catalog_product_id: str | None = None
    dimensions: Dimensions | None = None
    quantity: int | None = Field(default=None, gt=0, strict=True)
    processing: Processing | None = None
    price_basis: Literal["auto", "per_m2", "per_sheet", "unit"] | None = None
    customer_id: str | None = None
    kb_version: str | None = None


class QuoteReviseRequest(DatasetRequest):
    expected_revision: int = Field(ge=1)
    changes: QuoteChanges = Field(default_factory=QuoteChanges)
    reprice_current_kb: bool = False


class QuoteConfirmRequest(DatasetRequest):
    expected_revision: int = Field(ge=1)
    confirmed_by: str = Field(min_length=1, max_length=128)


class QuoteCancelRequest(DatasetRequest):
    expected_revision: int = Field(ge=1)
    reason: str = Field(default="", max_length=500)


class DimensionNormalizeRequest(DTO):
    text: str = Field(min_length=1, max_length=200)


class DimensionNormalizeResult(DTO):
    status: Literal["ok", "ambiguous", "invalid"]
    dimensions: Dimensions | None = None
    source_text: str
    source_unit: Literal["mm", "cm", "m"] | None = None
    normalized_text: str | None = None
    message_ru: str | None = None


class AssistantTurn(DatasetRequest):
    text: str = Field(min_length=1, max_length=16000)
    conversation_id: str | None = None
    customer_id: str | None = None
    kb_version: str
    inventory_mode: Literal["none", "free_whole_remnants", "replan"] = "free_whole_remnants"
    allow_ai: bool = True
    execution_mode: Literal["hybrid", "model_first"] = "hybrid"

    @model_validator(mode="after")
    def consistent_execution_mode(self):
        if self.execution_mode == "model_first" and not self.allow_ai:
            raise ValueError("model_first requires allow_ai=true")
        return self


class ModelAttempt(DTO):
    provider: str
    model_id: str
    status: Literal["ok", "error", "rejected"]
    error_kind: str | None = None


class ToolCallRecord(DTO):
    tool: str
    status: Literal["ok", "rejected", "error", "unavailable"]
    arguments: dict[str, object] = Field(default_factory=dict)
    summary: str = ""
    error_code: str | None = None


class VerifiedFact(DTO):
    fact_id: str
    kind: str
    value: str
    unit: str | None = None
    source_ref: str
    status: Literal["supported", "unsupported", "unknown"] = "supported"


class WorkingCard(DTO):
    intent: str
    catalog_product_id: str | None = None
    product_name: str | None = None
    confirmed_parameters: dict[str, str] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    missing_parameters: list[str] = Field(default_factory=list)
    normalized_dimensions: str | None = None
    facts: list[VerifiedFact] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    needs_manager: bool = False


class AssistantReply(DTO):
    conversation_id: str
    answer: str
    clarification: str | None = None
    quote: Quote | None = None
    evidence: list[Evidence]
    mode: Literal["online", "local_limited"]
    provider: str | None = None
    model_id: str | None = None
    answer_path: Literal["deterministic", "llm_tools", "fallback"] = "deterministic"
    status: Literal["answered", "clarification", "manager_handoff", "limited"] = "answered"
    card: WorkingCard | None = None
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    verifier_status: Literal["supported", "unsupported_replaced", "not_applicable"] = "supported"
    ai_unavailable_reason: str | None = None
    turn_index: int = 0
    latency_ms: int | None = None
    execution_mode: Literal["hybrid", "model_first"] = "hybrid"
    origin: Literal["model", "deterministic", "cache", "fallback", "reuse"] = "deterministic"
    cache_hit: bool = False
    model_call_count: int = 0
    model_attempts: list[ModelAttempt] = Field(default_factory=list)
    selected_provider: str | None = None
    selected_model_id: str | None = None
    verifier_reject_count: int = 0


class ConversationTurnView(DTO):
    turn_index: int
    user_text: str
    reply: AssistantReply
    created_at: str


class Conversation(DTO):
    conversation_id: str
    dataset_id: str
    customer_id: str | None
    context: dict[str, str]
    turns: list[ConversationTurnView]


class DialogRequest(DatasetRequest):
    id: str
    client: str
    manager: str
    kb_version: str


class PriceMention(DTO):
    raw: str
    amount_tg: MoneyString
    meaning: Literal["per_m2", "per_sheet", "retail_unit", "bulk_unit", "total", "unspecified"]


class DialogVerdict(DTO):
    id: str
    verdict: Literal["OK", "ERROR", "NEEDS_REVIEW"]
    correct: MoneyString | None = None
    evidence: list[Evidence]
    catalog_product_id: str | None = None
    reference_tg: MoneyString | None = None
    reference_meaning: str | None = None
    mentions: list[PriceMention] = Field(default_factory=list)
    reason_code: str | None = None
    explanation_ru: str | None = None
    input_sha256: str | None = None


class DialogRow(DTO):
    id: str = Field(min_length=1, max_length=128)
    client: str = Field(max_length=16000)
    manager: str = Field(max_length=16000)


class DialogBatchRequest(DatasetRequest):
    kb_version: str
    dialogs: list[DialogRow] = Field(min_length=1, max_length=1000)


class DialogBatchResult(DTO):
    dataset_id: str
    kb_version: str
    verdicts: list[DialogVerdict]
    complete: bool
    counts: dict[str, int]
    export_blockers: list[str]


class QuestionRow(DTO):
    id: str = Field(min_length=1, max_length=128)
    question: str = Field(max_length=16000)


class AnswerBatchRequest(DatasetRequest):
    kb_version: str
    questions: list[QuestionRow] = Field(min_length=1, max_length=1000)
    allow_ai: bool = True


class AnswerRow(DTO):
    id: str
    answer: str
    status: Literal["answered", "clarification", "manager_handoff", "limited", "failed"]
    answer_path: str
    provider: str | None = None
    model_id: str | None = None
    input_sha256: str
    evidence: list[Evidence] = Field(default_factory=list)


class AnswerBatchResult(DTO):
    dataset_id: str
    kb_version: str
    answers: list[AnswerRow]
    complete: bool
    counts: dict[str, int]
    export_blockers: list[str]


class AIProfileView(DTO):
    profile: str
    provider: Literal["gemini", "openrouter", "judge_gateway", "basisweb", "none"]
    model_id: str | None
    mode: Literal["free_only", "paid_enabled"]
    fallback_models: list[str] = Field(default_factory=list)
    key_configured: bool
    budget_limit_usd: MoneyString = "0"
    included_quota_enabled: bool = False
    quota_token_budget: int = 1_000_000
    quota_tokens_spent: int = 0
    limits: dict[str, int | None] = Field(default_factory=dict)


class AICheckRequest(DTO):
    profile: str = Field(default="default", max_length=64)
    live: bool = False


class AICheckResult(DTO):
    profile: str
    status: Literal["available", "no_key", "access_denied", "rate_limited", "unavailable", "invalid_profile"]
    provider: str
    model_id: str | None
    capabilities: dict[str, bool] = Field(default_factory=dict)
    quota: dict[str, int | None] = Field(default_factory=dict)
    message_ru: str
    live_checked: bool
    latency_ms: int | None = None
