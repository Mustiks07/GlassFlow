"""U06 immutable confirmation evidence, separate from plans, reserves and revenue."""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from .common import DTO, DatasetRequest, Identifier, MoneyString, NonnegativeInt


class MaterialUseRequest(DatasetRequest):
    subject_type: Literal["order", "basket"]
    subject_id: Identifier
    expected_version: NonnegativeInt
    execution_ref: Identifier
    execution_version: NonnegativeInt
    operator: Identifier
    note: str = Field(default="", max_length=2000)
    discrepancy_reason: str = Field(default="", max_length=2000)


class MaterialUseScope(DatasetRequest):
    subject_type: Literal["order", "basket"]
    subject_id: Identifier
    subject_revision: NonnegativeInt
    facts_hash: Identifier
    reservation_id: Identifier
    remnant_versions: dict[str, NonnegativeInt]


class MaterialUseAssessment(DTO):
    scope: MaterialUseScope
    execution_ref: Identifier
    execution_version: NonnegativeInt
    planned_area_mm2: NonnegativeInt
    actual_area_mm2: NonnegativeInt
    planned_material_value_tg: MoneyString
    actual_material_value_tg: MoneyString
    validation_ref: Identifier
    material_price_version: Identifier


class MaterialUseReceipt(DTO):
    assessment: MaterialUseAssessment
    confirmation_id: Identifier
    source_event_ref: Identifier
    reservation_state: Literal["consumed"]
    post_remnant_versions: dict[str, NonnegativeInt]
    confirmed_at: str

    @field_validator("confirmed_at")
    @classmethod
    def timestamp(cls, value):
        if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("Timezone required for the physical confirmation event")
        return value


class MaterialUseRecord(DatasetRequest):
    usage_id: Identifier
    receipt: MaterialUseReceipt
    operator: str
    note: str
    discrepancy_reason: str
    created_at: str
    receipt_hash: str


class MaterialUseSummary(DatasetRequest):
    confirmation_count: int
    planned_area_mm2: int
    actual_area_mm2: int
    planned_material_value_tg: str
    actual_material_value_tg: str
    usage_ids: list[str]
    source_event_refs: list[str]
    definition: str = "Подтвержденная оценка использованного материала; не выручка, прибыль или дополнительная к baseline выгода"
