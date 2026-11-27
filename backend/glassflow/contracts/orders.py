"""U01 shared order sheet. Canonical quote/stock remain owned by C3/C2."""

from typing import Literal

from pydantic import Field

from .common import DTO, DatasetRequest, Dimensions, Identifier, NonnegativeInt
from .cutting import Remnant
from .intelligence import Quote


class OrderFacts(DatasetRequest):
    quote: Quote
    remnant: Remnant
    requested_dimensions: Dimensions
    quantity: int = Field(gt=0, strict=True)
    kb_version: Identifier
    mapping_version: Identifier
    compatible: bool
    alternative_remnant_ids: list[str] = Field(default_factory=list)


class OrderReservation(DatasetRequest):
    reservation_id: Identifier
    order_id: Identifier
    order_revision: NonnegativeInt
    remnant_id: Identifier
    remnant_version: NonnegativeInt
    state: Literal["active", "released", "consumed"]


class OrderCreate(DatasetRequest):
    customer_ref: Identifier
    request_text: str = Field(min_length=1, max_length=8000)


class OrderAction(DatasetRequest):
    expected_version: NonnegativeInt
    operator: Identifier
    note: str = Field(default="", max_length=2000)


class OrderBind(OrderAction):
    quote_id: Identifier
    quote_revision: NonnegativeInt
    remnant_id: Identifier
    remnant_version: NonnegativeInt


class OrderReminderLink(OrderAction):
    reminder_id: Identifier


class OrderOffer(DTO):
    order_id: str
    revision: int
    facts_hash: str
    quote: Quote
    confirmed: bool


class WarehouseTask(DTO):
    order_id: str
    revision: int
    facts_hash: str
    material_id: str
    requested_dimensions: Dimensions
    quantity: int
    remnant: Remnant
    location_known: bool
    reservation: OrderReservation | None
    human_check: Literal["unchecked", "checked", "handed_over", "stale"]


class OrderSheet(OrderCreate):
    order_id: str
    version: NonnegativeInt = 0
    revision: NonnegativeInt = 0
    lifecycle: Literal["open", "handed_over", "cancelled"] = "open"
    quote_state: Literal["missing", "draft", "confirmed", "stale"] = "missing"
    warehouse_state: Literal["unchecked", "checked", "handed_over", "stale"] = "unchecked"
    facts: OrderFacts | None = None
    facts_hash: str | None = None
    reservation: OrderReservation | None = None
    reminder_ids: list[str] = Field(default_factory=list)
    stale_reason: str | None = None
    offer: OrderOffer | None = None
    warehouse_task: WarehouseTask | None = None
    created_at: str
    updated_at: str


class OrderHistory(DTO):
    event_id: int
    action: str
    recorded_at: str
    operator: str
    note: str
    sheet: OrderSheet
