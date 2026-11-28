"""N08/N09/N15 additive projections; original contest schemas stay unchanged."""

from typing import Literal

from pydantic import Field, model_validator

from .common import DTO, DatasetRequest, Identifier, NonnegativeInt
from .crm import ManagerMetrics

Dimension = Literal["product_group", "channel", "client_type"]
Manager = Literal["M1", "M2", "M3", "M4", "M5", "unknown"]
Metric = Literal["application_count", "mean_response_minutes", "conversion", "returns", "mean_sale_tg", "complaints", "discounts"]


class ComparableRequest(DatasetRequest):
    dimensions: list[Dimension] = Field(default_factory=lambda: ["product_group"], min_length=1, max_length=3)
    managers: list[Manager] = Field(default_factory=lambda: ["M1", "M2", "M3", "M4", "M5"])
    product_group: str | None = None
    channel: str | None = None
    client_type: str | None = None
    day_from: int | None = Field(default=None, ge=0)
    day_to: int | None = Field(default=None, ge=0)
    minimum_count: int = Field(default=10, ge=2, le=1000)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def consistent(self):
        if len(set(self.dimensions)) != len(self.dimensions) or len(set(self.managers)) != len(self.managers):
            raise ValueError("Dimensions and managers must be distinct")
        if not self.managers:
            raise ValueError("Choose at least one manager")
        if self.day_from is not None and self.day_to is not None and self.day_from > self.day_to:
            raise ValueError("Invalid day range")
        return self


class ComparableWarning(DTO):
    manager: str
    metric: str
    known_count: int
    total_count: int
    code: Literal["SMALL_GROUP", "INCOMPLETE", "NO_OBSERVATIONS"]


class ComparableGroup(DTO):
    dimensions: dict[str, str | None]
    application_count: int
    managers: list[ManagerMetrics]
    warnings: list[ComparableWarning]


class ComparableView(DatasetRequest):
    resolved: ComparableRequest
    total_groups: int
    matched_application_count: int
    groups: list[ComparableGroup]
    overall: list[ManagerMetrics]
    caveat_ru: str = "Состав заявок различается. Сравнение описательное; оно не устанавливает причины и не является рейтингом сотрудников."


class AnalyticsQuestion(DatasetRequest):
    question: str = Field(min_length=1, max_length=1000)


class AnalyticsAnswer(DTO):
    status: Literal["answered", "clarification"]
    metric: Metric | None = None
    answer_ru: str
    resolved: ComparableRequest | None = None
    comparison: ComparableView | None = None
    origin: Literal["deterministic_aggregates"] = "deterministic_aggregates"


class PieceLabelCreate(DatasetRequest):
    remnant_id: Identifier
    expected_version: NonnegativeInt
    operator: Identifier


class PieceLabel(DatasetRequest):
    label_id: str
    created_at: str
    printed_version: int
    operator: str
    snapshot: dict
    snapshot_hash: str
    scan_payload: str
    confirmation_note_ru: str = "Бирка идентифицирует кусок. Резерв, выдача и расход требуют отдельных актуальных проверок."


class PieceLabelResolved(DTO):
    label: PieceLabel
    current: dict
    changed: bool
    mutation_authorized_by_label: Literal[False] = False
