from typing import Literal

from pydantic import Field

from .common import DTO, DatasetRequest, Dimensions, Identifier, MoneyString, NonnegativeInt


class Material(DTO):
    material_id: Identifier
    name: str
    thickness_mm: int
    unit_price_tg: MoneyString
    tempered: bool


class Remnant(DTO):
    dataset_id: Identifier
    remnant_id: Identifier
    material_id: Identifier
    dimensions: Dimensions
    age_days: NonnegativeInt | None = None
    defect: bool
    location_raw: str
    status: Literal["available", "reserved", "consumed", "withdrawn"] = "available"
    version: NonnegativeInt = 0


class NewRemnant(DatasetRequest):
    material_id: Identifier
    dimensions: Dimensions
    defect: bool
    location_raw: str
    age_days: NonnegativeInt | None = None


class Part(DTO):
    part_id: Identifier
    order_id: Identifier
    material_id: Identifier
    dimensions: Dimensions
    premium: bool
    product_type: str = ""


class Placement(DTO):
    part_id: Identifier
    remnant_id: Identifier
    x_mm: NonnegativeInt | None = None
    y_mm: NonnegativeInt | None = None
    rot: Literal[0, 1] | None = None
    lock_kind: Literal["none", "assignment", "placement"] = "none"


class CutMetrics(DTO):
    covered_area_mm2: NonnegativeInt
    total_area_mm2: NonnegativeInt
    coverage: float = Field(ge=0, le=1)
    replacement_value_tg: MoneyString
    invalid: NonnegativeInt
    missing: NonnegativeInt
    fully_covered_orders: NonnegativeInt


class CutPlan(DatasetRequest):
    plan_id: Identifier
    revision: NonnegativeInt
    status: Literal["draft", "validated", "committed", "superseded", "invalid"]
    placements: list[Placement]
    metrics: CutMetrics
    free_original_remnant_ids: list[str]
    search_status: Literal["feasible", "optimal_in_pool", "proven_optimal", "limited", "infeasible"]


class SolverConfig(DTO):
    profile: Literal["quick", "standard", "extended"] = "standard"
    seed: int = 42
    time_limit_seconds: int = Field(default=60, gt=0)
    workers: int = Field(default=1, gt=0)
    minimum_free_remnants: int = Field(default=5, ge=0)


class SolveInput(DatasetRequest):
    materials: list[Material]
    remnants: list[Remnant]
    parts: list[Part]
    locks: list[Placement] = Field(default_factory=list)
    config: SolverConfig = Field(default_factory=SolverConfig)


class SolveRequest(DatasetRequest):
    base_plan_id: str | None = None
    locks: list[Placement] = Field(default_factory=list)
    config: SolverConfig = Field(default_factory=SolverConfig)


class FindRequest(DatasetRequest):
    material_id: Identifier
    dimensions: Dimensions
    premium: bool = False
    inventory_mode: Literal["free_whole_remnants", "replan"] = "free_whole_remnants"
    base_plan_id: str | None = None


class Candidate(DTO):
    remnant_id: Identifier
    remnant_version: NonnegativeInt
    x_mm: NonnegativeInt
    y_mm: NonnegativeInt
    rot: Literal[0, 1]
    location_raw: str


class Candidates(DTO):
    candidates: list[Candidate]
    reason_codes: list[str]
    scope: str


class ValidationResult(DTO):
    valid: bool
    errors: list[str]
    invalid_part_ids: list[str]
    missing_part_ids: list[str]


class CommitPlan(DatasetRequest):
    plan_revision: NonnegativeInt
    expected_remnant_versions: dict[str, NonnegativeInt]
