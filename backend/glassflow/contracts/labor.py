"""N05 actual measurement collection; elapsed time is not human active labor."""

from typing import Literal

from pydantic import Field

from .common import DTO, DatasetRequest, Identifier, MoneyString, NonnegativeInt
from .economics import LaborStudy


class LaborStudyCreate(DatasetRequest):
    name: str = Field(min_length=1, max_length=200)
    protocol: str = Field(min_length=1, max_length=1000)
    observer: Identifier
    start_definition: str = Field(min_length=1, max_length=1000)
    end_definition: str = Field(min_length=1, max_length=1000)


class MeasurementStart(DatasetRequest):
    expected_version: NonnegativeInt
    pair_id: Identifier
    task_id: Identifier
    task_input_ref: str = Field(min_length=1, max_length=2000)
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    operator: Identifier
    method: Literal["manual", "app"]
    planned_order: Literal["manual_first", "app_first"]


class MeasurementAction(DatasetRequest):
    expected_version: NonnegativeInt
    operator: Identifier
    note: str = Field(default="", max_length=2000)
    acknowledge_interruption: bool = False


class MeasurementFinish(MeasurementAction):
    result_ref: str = Field(min_length=1, max_length=2000)
    error_count: NonnegativeInt = 0
    rework_seconds: MoneyString = "0"


class MeasurementAttest(MeasurementAction):
    active_seconds: MoneyString
    human_confirmed: Literal[True]


class LaborMeasurement(DTO):
    measurement_id: str
    pair_id: str
    task_id: str
    task_input_ref: str
    input_hash: str
    operator: str
    method: Literal["manual", "app"]
    planned_order: Literal["manual_first", "app_first"]
    state: Literal["running", "paused", "finished", "attested"]
    started_at: str
    finished_at: str | None = None
    elapsed_seconds: str
    recorded_running_seconds: str
    attested_active_seconds: str | None = None
    attested_by: str | None = None
    human_confirmed: bool = False
    result_ref: str | None = None
    error_count: int = 0
    rework_seconds: str = "0"
    interruption_detected: bool = False
    interruption_acknowledged: bool = False
    events: list[dict]


class LaborPairStatus(DTO):
    pair_id: str
    task_id: str
    ready: bool
    reason_code: str | None
    saved_active_seconds: str | None = None


class LaborStudyView(LaborStudyCreate):
    study_id: str
    version: int
    created_at: str
    measurements: list[LaborMeasurement]
    pairs: list[LaborPairStatus]
    ready_pair_count: int
    export_ready: bool
    human_attestation_is_not_independent_verification: Literal[True] = True


class LaborStudyExport(DTO):
    study_id: str
    study_version: int
    measurement_status: Literal["supplied_measurements"] = "supplied_measurements"
    labor_studies: list[LaborStudy] = Field(min_length=10)
    pair_count: int
    negative_saving_pairs: int
    median_saved_active_seconds: str
    source_ref: str


class WorkflowItem(DTO):
    subject_type: Literal["order", "basket", "reminder"]
    subject_id: str
    version: int
    reason_code: str
    responsible_role: Literal["manager", "warehouse", "owner"]
    next_action: str
    route_hint: str
    summary: str
    amount_tg: str | None = None


class WorkflowQueue(DatasetRequest):
    items: list[WorkflowItem]
    counts: dict[str, int]
    projection_only: Literal[True] = True
