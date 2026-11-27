"""U04 platform coordination DTOs; C3 owns requests/prices, C2 owns joint stock selection."""

from typing import Literal

from pydantic import Field, model_validator

from .common import DTO, DatasetRequest, Identifier, MoneyString, NonnegativeInt
from .intelligence import Quote, QuoteRequest
from .orders import OrderAction


class BasketLineDraft(DTO):
    line_id: Identifier
    text: str = Field(min_length=1, max_length=4000)
    request: QuoteRequest | None = None
    clarification: str | None = Field(default=None, max_length=2000)


class BasketCreate(DatasetRequest):
    customer_ref: Identifier
    request_text: str = Field(min_length=1, max_length=16000)
    lines: list[BasketLineDraft] = Field(default_factory=list, max_length=100)


class BasketLinesUpdate(OrderAction):
    lines: list[BasketLineDraft] = Field(min_length=1, max_length=100)


class BasketLineRef(DTO):
    line_id: Identifier
    quote_id: Identifier | None = None
    quote_revision: NonnegativeInt | None = None

    @model_validator(mode="after")
    def paired(self):
        if (self.quote_id is None) != (self.quote_revision is None):
            raise ValueError("Quote ID and revision must be supplied together")
        return self


class BasketBind(OrderAction):
    lines: list[BasketLineRef] = Field(min_length=1, max_length=100)
    selection_ref: Identifier | None = None
    selection_version: NonnegativeInt | None = None

    @model_validator(mode="after")
    def paired(self):
        if (self.selection_ref is None) != (self.selection_version is None):
            raise ValueError("Selection ref and version must be supplied together")
        return self


class BasketLineFacts(DTO):
    line_id: Identifier
    kind: Literal["glass", "catalog", "unresolved"]
    quote: Quote | None = None
    quote_customer_ref: Identifier | None = None
    source_request_hash: str | None = None
    compatibility: Literal["confirmed", "not_required", "needs_review"] = "needs_review"
    clarification: str | None = None


class BasketStockFacts(DatasetRequest):
    basket_id: Identifier
    input_hash: Identifier
    selection_ref: Identifier
    selection_version: NonnegativeInt
    line_ids: list[Identifier]
    remnant_versions: dict[str, NonnegativeInt]
    validated: bool
    validation_ref: Identifier
    planned_area_mm2: NonnegativeInt
    planned_material_value_tg: MoneyString


class BasketFacts(DatasetRequest):
    basket_id: Identifier
    input_hash: Identifier
    lines: list[BasketLineFacts] = Field(min_length=1, max_length=100)
    stock: BasketStockFacts | None = None


class BasketReservation(DatasetRequest):
    reservation_id: Identifier
    basket_id: Identifier
    basket_revision: NonnegativeInt
    selection_ref: Identifier
    selection_version: NonnegativeInt
    remnant_versions: dict[str, NonnegativeInt]
    state: Literal["active", "released", "consumed"]


class Basket(BasketCreate):
    basket_id: str
    version: NonnegativeInt = 0
    revision: NonnegativeInt = 0
    state: Literal["draft", "needs_review", "ready", "confirmed", "reserved", "checked", "handed_over", "completed", "stale", "cancelled"] = "draft"
    input_hash: str
    binding: BasketBind | None = None
    facts: BasketFacts | None = None
    facts_hash: str | None = None
    total_tg: MoneyString | None = None
    known_subtotal_tg: MoneyString | None = None
    issues: list[str] = Field(default_factory=list)
    reservation: BasketReservation | None = None
    material_use_id: str | None = None
    created_at: str
    updated_at: str


class BasketParseResult(DatasetRequest):
    basket_id: Identifier
    basket_version: NonnegativeInt
    input_hash: Identifier
    lines: list[BasketLineDraft] = Field(min_length=1, max_length=100)
    warnings: list[str] = Field(default_factory=list)


class BasketApplyParse(OrderAction):
    job_id: Identifier


class BasketHistory(DTO):
    event_id: int
    action: str
    recorded_at: str
    operator: str
    note: str
    basket: Basket
