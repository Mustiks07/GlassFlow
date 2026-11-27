from typing import Literal

from pydantic import Field

from .common import DTO, DatasetRequest, Identifier, MoneyString


class RankRequest(DatasetRequest):
    policy: Literal["reference", "validated_model"] = "reference"


class RankedApplication(DTO):
    app_id: str
    client_id: str
    priority: float
    reasons: list[str]


class Ranking(DTO):
    rows: list[RankedApplication]
    unique_client_count: int
    policy: str
    observed_precision: float | None = None


class ReminderRequest(DatasetRequest):
    recipient_client_id: Identifier
    source_app_ids: list[str]
    subject_type: Literal["interest", "quote_example", "specific_remnant"]
    subject_ref: str | None = None
    due_at: str | None = None
    owner: str


class Reminder(ReminderRequest):
    reminder_id: str
    version: int
    state: Literal["draft", "scheduled", "due", "done", "cancelled", "stale"]
    subject_version: int | None = None


class Ratio(DTO):
    numerator: int
    denominator: int
    value: float | None


class ManagerMetrics(DTO):
    manager: str
    application_count: int
    mean_response_minutes: float | None
    conversion: Ratio
    returns: Ratio
    mean_sale_tg: MoneyString | None
    mean_application_tg: MoneyString | None
    complaints: Ratio
    discounts: Ratio


class Buyer(DTO):
    name: str
    city: str
    category: str
    url: str
    why: str
    source_url: str
    score: int = Field(ge=0, le=100)


class CardsRequest(DatasetRequest):
    plan_id: str
    plan_revision: int
    buyer_registry_version: str


class SaleCard(DTO):
    remnant_id: str
    title: str
    price_tg: MoneyString
    description: str
    target_buyer: str
    top3_buyers: list[str] = Field(min_length=3, max_length=3)
