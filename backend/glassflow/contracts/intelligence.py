from typing import Literal

from pydantic import Field

from .common import DTO, DatasetRequest, Dimensions, Evidence, Identifier, MoneyString


class CatalogPrice(DTO):
    price_type: Literal["per_m2", "per_sheet", "retail_unit", "bulk_unit", "per_m"]
    amount_tg: MoneyString | None
    minimum_quantity: int | None = None


class CatalogProduct(DTO):
    catalog_product_id: Identifier
    name: str
    category: str
    prices: list[CatalogPrice]
    evidence: list[Evidence]


class Processing(DTO):
    kind: Literal["none", "euro_edge", "facet", "sandblast"] = "none"
    sides: Literal["all", "selected"] = "all"
    selected_sides: list[Literal["left", "right", "top", "bottom"]] = Field(default_factory=list)


class QuoteRequest(DatasetRequest):
    catalog_product_id: Identifier
    dimensions: Dimensions | None = None
    quantity: int = Field(default=1, gt=0, strict=True)
    processing: Processing = Field(default_factory=Processing)
    kb_version: str
    customer_id: str | None = None


class QuoteLine(DTO):
    label: str
    amount_tg: MoneyString
    evidence: list[Evidence]


class Quote(DatasetRequest):
    quote_id: Identifier
    revision: int
    status: Literal["calculated", "needs_review", "ready", "confirmed"]
    components: list[QuoteLine]
    total_tg: MoneyString | None
    preliminary: bool = True
    clarification: str | None = None
    material_mapping_status: Literal["confirmed", "unmapped", "ambiguous"]
    material_id: str | None = None


class AssistantTurn(DatasetRequest):
    text: str = Field(min_length=1, max_length=16000)
    conversation_id: str | None = None
    customer_id: str | None = None
    kb_version: str


class AssistantReply(DTO):
    conversation_id: str
    answer: str
    clarification: str | None = None
    quote: Quote | None = None
    evidence: list[Evidence]
    mode: Literal["online", "local_limited"]
    provider: str | None = None
    model_id: str | None = None


class DialogRequest(DatasetRequest):
    id: str
    client: str
    manager: str
    kb_version: str


class DialogVerdict(DTO):
    id: str
    verdict: Literal["OK", "ERROR", "NEEDS_REVIEW"]
    correct: MoneyString | None = None
    evidence: list[Evidence]
