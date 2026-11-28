"""Cutting / inventory transport contracts (owner: Claude 2).

Foundation fields are kept with their meaning; everything else is additive with defaults.
Geometry is integer millimetres; money is a decimal string. Codes are stable API values.
"""

from typing import Literal

from pydantic import Field

from .common import DTO, DatasetRequest, Dimensions, Identifier, MoneyString, NonnegativeInt

RemnantStatus = Literal["available", "reserved", "consumed", "withdrawn"]
LockKind = Literal["none", "assignment", "placement"]
SearchStatus = Literal["feasible", "optimal_in_pool", "proven_optimal", "limited", "infeasible"]


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
    status: RemnantStatus = "available"
    version: NonnegativeInt = 0
    internal_id: str | None = None
    """Technical UUID; ``remnant_id`` is the external ID, unique only inside ``dataset_id``."""
    origin: Literal["source", "working", "child"] = "source"
    original: bool = True
    """True for pieces of the imported stock (eligible for the five contest sale cards)."""
    rack: str | None = None
    cell: str | None = None
    parent_remnant_id: str | None = None
    active_reservation_id: str | None = None
    status_reason: str | None = None


class RemnantPage(DTO):
    items: list[Remnant]
    total: NonnegativeInt
    limit: NonnegativeInt
    offset: NonnegativeInt


class NewRemnant(DatasetRequest):
    material_id: Identifier
    dimensions: Dimensions
    defect: bool
    location_raw: str = Field(min_length=1)
    age_days: NonnegativeInt | None = None
    remnant_id: Identifier | None = None
    """Optional external ID; generated (W-xxxx) when omitted. Must be unique in the dataset."""


class RemnantUpdate(DatasetRequest):
    expected_version: NonnegativeInt
    location_raw: str | None = Field(default=None, min_length=1)
    defect: bool | None = None
    age_days: NonnegativeInt | None = None
    reason: str = ""


class MeasurementUpdate(DatasetRequest):
    expected_version: NonnegativeInt
    dimensions: Dimensions
    previous_dimensions: Dimensions | None = None
    """Explicitly entered previous measurement; compared with the stored one (no hidden allowances)."""
    reason: str = ""


class WithdrawRequest(DatasetRequest):
    expected_version: NonnegativeInt
    reason: str = Field(min_length=1)


class ConsumeRequest(DatasetRequest):
    expected_version: NonnegativeInt
    reservation_id: Identifier
    reason: str = ""


class ReleaseRequest(DatasetRequest):
    expected_version: NonnegativeInt
    reason: str = ""


class ReserveRequest(DatasetRequest):
    """Whole-piece reservation after an explicit manager confirmation (e.g. a confirmed quote)."""

    expected_version: NonnegativeInt
    owner_context: str = Field(min_length=1, max_length=256)
    material_id: Identifier
    dimensions: Dimensions
    premium: bool = False
    x_mm: NonnegativeInt | None = None
    y_mm: NonnegativeInt | None = None
    rot: Literal[0, 1] | None = None


class ChildRemnant(DTO):
    dimensions: Dimensions
    location_raw: str = Field(min_length=1)
    remnant_id: Identifier | None = None


class ChildRemnantsRequest(DatasetRequest):
    expected_version: NonnegativeInt
    children: list[ChildRemnant] = Field(min_length=1)


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
    lock_kind: LockKind = "none"


class MaterialValue(DTO):
    material_id: Identifier
    covered_area_mm2: NonnegativeInt
    unit_price_tg: MoneyString
    value_tg: MoneyString


class CutMetrics(DTO):
    covered_area_mm2: NonnegativeInt
    total_area_mm2: NonnegativeInt
    coverage: float = Field(ge=0, le=1)
    replacement_value_tg: MoneyString
    """Valuation of replaced new glass at materials.csv rates. Not profit."""
    invalid: NonnegativeInt
    missing: NonnegativeInt
    fully_covered_orders: NonnegativeInt
    total_orders: NonnegativeInt = 0
    covered_parts: NonnegativeInt = 0
    total_parts: NonnegativeInt = 0
    used_original_remnants: NonnegativeInt = 0
    free_original_remnants: NonnegativeInt = 0
    used_remnants: NonnegativeInt = 0
    score: float = 0.0
    """Contest cutting score formula (TZ 11) on this dataset; not an official jury result."""
    coverage_percent: str = "0"
    """Exact decimal percentage string (numerator/denominator) to avoid float rounding."""
    value_by_material: list[MaterialValue] = Field(default_factory=list)
    new_reasons: dict[str, str] = Field(default_factory=dict)
    """part_id -> reason code for NEW parts."""


class PlanIssue(DTO):
    code: str
    message_ru: str
    part_id: str | None = None
    remnant_id: str | None = None
    other_part_id: str | None = None
    coordinates: dict[str, int] = Field(default_factory=dict)


class SolverConfig(DTO):
    profile: Literal["quick", "standard", "extended"] = "standard"
    seed: int = 42
    time_limit_seconds: int = Field(default=60, gt=0)
    workers: int = Field(default=1, gt=0)
    minimum_free_remnants: int = Field(default=5, ge=0)
    fixed_work: bool = False
    max_pool_patterns: int = Field(default=80_000, gt=0)


class CutPlan(DatasetRequest):
    plan_id: Identifier
    revision: NonnegativeInt
    status: Literal["draft", "validated", "committed", "superseded", "invalid"]
    placements: list[Placement]
    metrics: CutMetrics
    free_original_remnant_ids: list[str]
    search_status: SearchStatus
    parent_plan_id: str | None = None
    parent_revision: NonnegativeInt | None = None
    stop_reason: str = "completed"
    config: SolverConfig | None = None
    issues: list[PlanIssue] = Field(default_factory=list)
    evidence: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    created_at: str | None = None
    source: Literal["solver", "edit", "import"] = "solver"
    requested_locks: list[Placement] = Field(default_factory=list)
    """Lock constraints of the task. Persisted with every revision and enforced by validate/commit/export
    until removed by an explicit edit. A plan violating one of them is ``invalid`` even if its geometry is ok."""
    inventory_version: str = ""
    """Inventory token when this revision was stored; ``metrics``/``free_original_remnant_ids`` are as of then."""
    inventory_current: bool | None = None
    """False when the stock changed since the revision was stored: re-check via export or free-remnants."""


class PlanSummary(DTO):
    plan_id: str
    revision: NonnegativeInt
    status: str
    search_status: str
    coverage: float
    covered_area_mm2: NonnegativeInt
    created_at: str | None = None
    source: str


class SolveInput(DatasetRequest):
    materials: list[Material]
    remnants: list[Remnant]
    parts: list[Part]
    locks: list[Placement] = Field(default_factory=list)
    config: SolverConfig = Field(default_factory=SolverConfig)
    unavailable_remnant_ids: list[str] = Field(default_factory=list)
    """Reserved by other plans / consumed / withdrawn / excluded for this run."""
    occupied_remnant_ids: list[str] = Field(default_factory=list)
    """Whole pieces occupied by production in the no-replan mode."""
    previous_placements: list[Placement] = Field(default_factory=list)
    """Active plan placements, used only as the stability tie-breaker."""
    base_plan_id: str | None = None
    base_revision: NonnegativeInt | None = None


class SolveRequest(DatasetRequest):
    base_plan_id: str | None = None
    locks: list[Placement] = Field(default_factory=list)
    config: SolverConfig = Field(default_factory=SolverConfig)
    excluded_remnant_ids: list[str] = Field(default_factory=list)
    mode: Literal["replan", "keep_committed"] = "replan"
    """keep_committed: whole pieces used by the committed plan are occupied and locked as they are."""


class FindRequest(DatasetRequest):
    material_id: Identifier
    dimensions: Dimensions
    premium: bool = False
    inventory_mode: Literal["free_whole_remnants", "replan"] = "free_whole_remnants"
    base_plan_id: str | None = None
    quantity: int = Field(default=1, ge=1, le=50)


class Candidate(DTO):
    remnant_id: Identifier
    remnant_version: NonnegativeInt
    x_mm: NonnegativeInt
    y_mm: NonnegativeInt
    rot: Literal[0, 1]
    location_raw: str
    copy_index: NonnegativeInt = 0
    remnant_dimensions: Dimensions | None = None
    waste_area_mm2: NonnegativeInt = 0
    age_days: NonnegativeInt | None = None
    shares_remnant_with_plan: bool = False


class Candidates(DTO):
    candidates: list[Candidate]
    reason_codes: list[str]
    scope: str
    covered_quantity: NonnegativeInt = 0
    requested_quantity: NonnegativeInt = 1
    reasons_ru: list[str] = Field(default_factory=list)
    inventory_version: str = ""
    """Opaque token of the stock state used; consumers re-check before confirming anything."""


class ValidationResult(DTO):
    valid: bool
    errors: list[str]
    invalid_part_ids: list[str]
    missing_part_ids: list[str]
    issues: list[PlanIssue] = Field(default_factory=list)
    plan_revision: NonnegativeInt | None = None


class CommitPlan(DatasetRequest):
    plan_revision: NonnegativeInt
    expected_remnant_versions: dict[str, NonnegativeInt]
    owner_context: str = ""


class Reservation(DTO):
    reservation_id: str
    dataset_id: str
    remnant_id: str
    plan_id: str
    plan_revision: NonnegativeInt
    owner_context: str
    status: Literal["active", "released", "consumed"]
    version: NonnegativeInt
    created_at: str
    released_at: str | None = None
    consumed_at: str | None = None
    part_ids: list[str] = Field(default_factory=list)


class CommitResult(DTO):
    plan: CutPlan
    reservations: list[Reservation]
    released_reservation_ids: list[str] = Field(default_factory=list)
    superseded_plan: str | None = None


class InventoryChange(DTO):
    """Result of reserve/consume/release/withdraw: the new state and the audit event id."""

    remnant: Remnant
    reservation: Reservation | None = None
    audit_event_id: str
    children: list[Remnant] = Field(default_factory=list)


class DraftEdit(DTO):
    part_id: Identifier
    action: Literal["move", "unplace", "lock", "unlock"] = "move"
    remnant_id: Identifier | None = None
    x_mm: NonnegativeInt | None = None
    y_mm: NonnegativeInt | None = None
    rot: Literal[0, 1] | None = None
    lock_kind: LockKind | None = None


class DraftRequest(DatasetRequest):
    base_revision: NonnegativeInt
    edits: list[DraftEdit] = Field(min_length=1)


class DraftResult(DTO):
    plan: CutPlan
    validation: ValidationResult


class PlanRef(DTO):
    plan_id: str
    revision: NonnegativeInt | None = None


class CompareRequest(DatasetRequest):
    base: PlanRef
    candidate: PlanRef


class PlacementChange(DTO):
    part_id: str
    before: Placement | None
    after: Placement | None
    kind: Literal["added", "removed", "moved", "reassigned", "unchanged"]


class PlanComparison(DTO):
    dataset_id: str
    base: PlanRef
    candidate: PlanRef
    delta_covered_area_mm2: int
    delta_coverage: float
    delta_value_tg: str
    delta_fully_covered_orders: int
    delta_free_original_remnants: int
    newly_new_part_ids: list[str]
    newly_covered_part_ids: list[str]
    changes: list[PlacementChange]
    affected_reserved_remnant_ids: list[str]


class ImpactRequest(DatasetRequest):
    remnant_id: Identifier
    change: Literal["exclude", "measurement"]
    dimensions: Dimensions | None = None
    plan_id: str | None = None


class ImpactReport(DTO):
    dataset_id: str
    remnant_id: str
    remnant_version: NonnegativeInt
    plan_id: str | None
    plan_revision: NonnegativeInt | None
    affected_part_ids: list[str]
    new_part_ids: list[str]
    delta_covered_area_mm2: int
    delta_value_tg: str
    affected_reservation_ids: list[str]
    affected_order_ids: list[str]
    requires_commit: bool = True
    note_ru: str = ""


class LayoutPart(DTO):
    part_id: str
    order_id: str
    x_mm: int
    y_mm: int
    w_mm: int
    h_mm: int
    rot: Literal[0, 1]
    lock_kind: LockKind = "none"
    premium: bool = False


class RemnantLayout(DTO):
    remnant_id: str
    material_id: str
    length_mm: int
    width_mm: int
    trim_mm: int
    gap_mm: int
    tempered: bool
    tempered_tolerance_mm: int = 2
    defect: bool
    location_raw: str
    rack: str | None = None
    cell: str | None = None
    parts: list[LayoutPart]
    used_area_mm2: int


class PlanLayout(DTO):
    plan_id: str
    revision: NonnegativeInt
    remnants: list[RemnantLayout]
    new_part_ids: list[str]


class ExportRow(DTO):
    part_id: str
    remnant_id: str
    x_mm: str
    y_mm: str
    rot: str


class SolutionExport(DTO):
    """Rows for solution.csv in input order plus metadata; Pro serialises and re-runs validators.

    Semantics: LIVE. Validation, ``metrics`` and ``free_original_remnant_ids`` are computed in one read of the
    current stock at ``as_of`` / ``inventory_version``. The historical list stored with the revision is
    separate (``plan_free_original_remnant_ids``) and must not be used for sale cards.
    """

    dataset_id: str
    plan_id: str
    revision: NonnegativeInt
    header: list[str]
    rows: list[ExportRow]
    metrics: CutMetrics
    free_original_remnant_ids: list[str]
    validation: ValidationResult
    as_of: str = ""
    inventory_version: str = ""
    plan_inventory_version: str = ""
    inventory_changed_since_plan: bool = False
    plan_free_original_remnant_ids: list[str] = Field(default_factory=list)
    no_longer_free_remnant_ids: list[str] = Field(default_factory=list)
    minimum_free_remnants: NonnegativeInt = 5
    minimum_free_remnants_met: bool = True


class FreeRemnant(DTO):
    remnant_id: str
    version: NonnegativeInt
    material_id: str
    dimensions: Dimensions
    defect: bool
    location_raw: str


class FreeRemnantsCheck(DTO):
    """Final re-check before a sale card / confirmation: fully free ORIGINAL pieces of a plan, now."""

    dataset_id: str
    plan_id: str
    revision: NonnegativeInt
    plan_status: str
    as_of: str
    inventory_version: str
    free_original: list[FreeRemnant]
    count: NonnegativeInt
    minimum_free_remnants: NonnegativeInt
    minimum_free_remnants_met: bool
    plan_free_original_remnant_ids: list[str]
    no_longer_free_remnant_ids: list[str]


class AuditEvent(DTO):
    event_id: str
    dataset_id: str
    action: str
    object_type: str
    object_id: str
    before_version: int | None
    after_version: int | None
    actor: str
    correlation_id: str
    created_at: str
    details: dict[str, str | int | float | bool | None | list[str]] = Field(default_factory=dict)


class NewRequirement(DTO):
    material_id: str
    dimensions: Dimensions
    quantity: NonnegativeInt
    part_ids: list[str]
    order_ids: list[str]
    area_mm2: NonnegativeInt
    reason_code: str
    reason_ru: str


class NewRequirements(DatasetRequest):
    plan_id: str
    revision: NonnegativeInt
    plan_status: str
    is_active: bool
    scope: Literal['active', 'proposal', 'historical']
    inventory_version: str
    rows: list[NewRequirement]
    total_area_mm2: NonnegativeInt
    total_quantity: NonnegativeInt
    disclaimer_ru: str = 'Потребность в деталях NEW; число новых листов и закупочная цена не определены.'


class PlacementMargin(DTO):
    part_id: str
    remnant_id: str
    tempered: bool
    margin_kind: Literal['cut_geometry', 'whole_piece_tolerance']
    edge_clearance_mm: int | None = None
    neighbor_clearance_mm: int | None = None
    minimum_excess_mm: int
    dimension_deviation_mm: int | None = None


class PlanMargins(DatasetRequest):
    plan_id: str
    revision: NonnegativeInt
    inventory_version: str
    placements: list[PlacementMargin]
    trim_mm: int = 5
    gap_mm: int = 3
    tempered_tolerance_mm: int = 2
    note_ru: str = 'Геометрический запас по текущему замеру, не вероятность брака. Конкурсные допуски не изменены.'


class SaleReadiness(DatasetRequest):
    status: Literal['ready_unchanged', 'ready_alternative', 'tradeoff_available', 'evidence_shortage', 'limited', 'cancelled', 'stale']
    baseline: CutPlan
    alternative: CutPlan | None = None
    tradeoff: CutPlan | None = None
    eligible_original_ids: list[str]
    baseline_free_eligible_ids: list[str]
    candidate_free_eligible_ids: list[str] = Field(default_factory=list)
    registry_version: str
    input_fingerprint: str
    inventory_fingerprint: str
    registry_fingerprint: str
    minimum_free: int = 5
    delta_area_mm2: int | None = None
    search_performed: bool = False
    elapsed_seconds: float = 0
    reason_ru: str


class ScarcityRequest(FindRequest):
    budget_ms: int = Field(default=300, ge=1, le=3000)


class ScarcityExplanation(DTO):
    preserve_remnant_id: str
    alternative_remnant_id: str
    known_order_id: str
    pending_part_ids: list[str]
    joint_witness: list[Placement]
    request_part_ids: list[str] = Field(default_factory=list)
    reason_ru: str


class ScarcityResult(DatasetRequest):
    baseline: Candidates
    status: Literal['proved', 'no_proof', 'limited', 'not_applicable']
    recommended_remnant_id: str | None = None
    explanations: list[ScarcityExplanation] = Field(default_factory=list)
    elapsed_ms: float
    inventory_version: str
    plan_id: str | None = None
    plan_revision: int | None = None
    baseline_order_preserved: bool = True
    pending_basis: str = 'uncovered_parts_of_selected_plan_or_imported_orders_without_plan'
