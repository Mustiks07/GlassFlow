from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator

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
    policy_version: str = "reference-v1"
    grouped_clients: dict[str, list[str]] = Field(default_factory=dict)
    target_definition: str = "Новое обращение в течение 60 дней; не покупка и не выручка"


class ReminderRequest(DatasetRequest):
    recipient_client_id: Identifier
    source_app_ids: list[str]
    subject_type: Literal["interest", "quote_example", "specific_remnant"]
    subject_ref: str | None = None
    due_at: str | None = None
    owner: str
    subject_version: int | None = Field(default=None, ge=0, strict=True)
    compatibility_ref: str | None = None
    compatibility_version: int | None = Field(default=None, ge=0, strict=True)
    text: str = Field(default="", max_length=4000)
    active_period: str | None = Field(default=None, max_length=100)

    @field_validator("due_at")
    @classmethod
    def utc_timestamp(cls, value):
        if value is None:
            return None
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            raise ValueError("Нужен timestamp с часовым поясом")
        return moment.astimezone(UTC).isoformat()


class Reminder(ReminderRequest):
    reminder_id: str
    version: int
    state: Literal["draft", "scheduled", "due", "done", "cancelled", "stale"]
    stale_reason: str | None = None


class ReminderUpdate(DTO):
    dataset_id: Identifier
    expected_version: int = Field(ge=0, strict=True)
    due_at: str | None = None
    owner: str | None = None
    text: str | None = Field(default=None, max_length=4000)
    state: Literal["done"] | None = None


class MetricEvidence(DTO):
    numerator: str | None
    denominator: int
    source_app_ids: list[str]
    known_app_ids: list[str]
    source_rows: list[int]
    total: int
    completeness: float | None
    definition: str


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
    evidence: dict[str, MetricEvidence] = Field(default_factory=dict)
    source_manager_values: list[str] = Field(default_factory=list)


class Buyer(DTO):
    name: str
    city: str
    category: str
    url: str
    why: str
    source_url: str
    score: int = Field(ge=0, le=100)
    buyer_id: str | None = None


class CardsRequest(DatasetRequest):
    plan_id: str
    plan_revision: int
    buyer_registry_version: str
    factor: MoneyString = "0.50"


class SaleCard(DTO):
    remnant_id: str
    title: str
    price_tg: MoneyString
    description: str
    target_buyer: str
    top3_buyers: list[str] = Field(min_length=3, max_length=3)
    card_id: str | None = None
    dataset_id: str | None = None
    plan_id: str | None = None
    plan_revision: int | None = None
    remnant_version: int | None = None
    buyer_registry_version: str | None = None
    version: int = 0
    status: Literal["draft", "ready", "stale"] = "draft"
    factor: MoneyString = "0.50"
    top3_buyer_ids: list[str] = Field(default_factory=list)
    assumptions: str = "Коэффициент - проектное допущение, не рыночная оценка и не факт продажи"


class CardUpdate(DatasetRequest):
    expected_version: int = Field(ge=0, strict=True)
    factor: MoneyString | None = None
    top3_buyer_ids: list[str] | None = Field(default=None, min_length=3, max_length=3)
