"""HTTP routes of the cutting / inventory domain (prefix ``/api/v1`` is added by ``main``).

Every route calls ``CuttingService``; the same service backs AI tools and exports. Errors use the
common ``ApiError`` body. Heavy solving goes through the platform job submitter
(``app.state.job_submitter``, see ``JobSubmitter``); without it ``/cutting/solve`` answers 503 instead
of pretending to run.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from glassflow.contracts.common import ApiError
from glassflow.contracts.cutting import (
    AuditEvent,
    Candidates,
    ChildRemnantsRequest,
    CommitPlan,
    CommitResult,
    CompareRequest,
    ConsumeRequest,
    CutPlan,
    DraftRequest,
    DraftResult,
    FindRequest,
    FreeRemnantsCheck,
    ImpactReport,
    ImpactRequest,
    InventoryChange,
    MeasurementUpdate,
    NewRemnant,
    PlanComparison,
    PlanLayout,
    PlanSummary,
    ReleaseRequest,
    Remnant,
    RemnantPage,
    RemnantUpdate,
    ReserveRequest,
    SolutionExport,
    SolveInput,
    SolveRequest,
    ValidationResult,
    WithdrawRequest,
)
from glassflow.contracts.platform import Job

from .service import CuttingError, CuttingService
from .uow import read_session, write_transaction

ERRORS = {code: {"model": ApiError} for code in (404, 409, 422, 503)}
router = APIRouter(tags=["cutting"], responses=ERRORS)

IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)]


class JobSubmitter(Protocol):
    """Provided by the platform (Pro). ``payload`` is a serialisable ``SolveInput``.

    The worker calls ``CuttingEngine().solve(SolveInput, JobContext)``; on completion the single
    coordinator calls ``CuttingService(session).store_solver_plan(dataset_id, plan, base_plan_id=...)``.
    """

    def submit(self, kind: str, dataset_id: str, payload: dict) -> Job: ...


def _error(exc: CuttingError, correlation_id: str) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content=ApiError(
        code=exc.code, message_ru=exc.message_ru, field_errors=exc.field_errors,
        conflict_objects=exc.conflict_objects, retryable=exc.retryable, correlation_id=correlation_id,
    ).model_dump())


def _run(request: Request, fn: Callable[[CuttingService], object], *, write: bool):
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    factory = request.app.state.session_factory
    try:
        with (write_transaction(factory) if write else read_session(factory)) as session:
            return fn(CuttingService(session, correlation_id=correlation_id))
    except CuttingError as exc:
        return _error(exc, correlation_id)
    except OperationalError:  # SQLite busy beyond busy_timeout: a concurrent writer holds the lock
        return _error(CuttingError(409, "CONCURRENT_UPDATE", "База занята параллельной операцией; повторите.",
                                   retryable=True), correlation_id)


# ------------------------------------------------------------------------------------------ remnants
@router.get("/remnants", response_model=list[Remnant])
def list_remnants(request: Request, dataset_id: str, material_id: str | None = None, status: str | None = None,
                  limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0)] = 0):
    def go(s: CuttingService):
        page = s.list_remnants(dataset_id, material_id=material_id, status=status, limit=limit, offset=offset)
        return JSONResponse([r.model_dump(mode="json") for r in page.items], headers={"X-Total-Count": str(page.total)})

    return _run(request, go, write=False)


@router.get("/datasets/{dataset_id}/remnants", response_model=RemnantPage)
def list_remnants_page(
    request: Request, dataset_id: str, material_id: str | None = None,
    status: Literal["available", "reserved", "consumed", "withdrawn"] | None = None, defect: bool | None = None,
    original: bool | None = None, min_length_mm: Annotated[int | None, Query(gt=0)] = None,
    min_width_mm: Annotated[int | None, Query(gt=0)] = None, search: Annotated[str | None, Query(max_length=64)] = None,
    sort: Literal["remnant_id", "area", "age_days", "material_id", "status", "source_order"] = "source_order",
    descending: bool = False, limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0)] = 0,
):
    return _run(request, lambda s: s.list_remnants(
        dataset_id, material_id=material_id, status=status, defect=defect, original=original,
        min_length_mm=min_length_mm, min_width_mm=min_width_mm, search=search, sort=sort, descending=descending,
        limit=limit, offset=offset), write=False)


@router.get("/remnants/{remnant_id}", response_model=Remnant)
def get_remnant(request: Request, remnant_id: str, dataset_id: str):
    return _run(request, lambda s: s.get_remnant(dataset_id, remnant_id), write=False)


@router.post("/remnants", response_model=Remnant)
def add_remnant(request: Request, body: NewRemnant):
    return _run(request, lambda s: s.add_remnant(body), write=True)


@router.post("/datasets/{dataset_id}/remnants", response_model=Remnant)
def add_remnant_scoped(request: Request, dataset_id: str, body: NewRemnant):
    if body.dataset_id != dataset_id:
        return _error(CuttingError(422, "DATASET_MISMATCH", "dataset_id в пути и теле не совпадают."), str(uuid.uuid4()))
    return _run(request, lambda s: s.add_remnant(body), write=True)


@router.patch("/remnants/{remnant_id}", response_model=Remnant)
def update_remnant(request: Request, remnant_id: str, body: RemnantUpdate):
    return _run(request, lambda s: s.update_remnant(remnant_id, body), write=True)


@router.patch("/remnants/{remnant_id}/measurement", response_model=ImpactReport)
def update_measurement(request: Request, remnant_id: str, body: MeasurementUpdate):
    return _run(request, lambda s: s.update_measurement(remnant_id, body)[1], write=True)


@router.post("/remnants/{remnant_id}/withdraw", response_model=InventoryChange)
def withdraw_remnant(request: Request, remnant_id: str, body: WithdrawRequest):
    return _run(request, lambda s: s.withdraw(remnant_id, body), write=True)


@router.post("/remnants/{remnant_id}/restore", response_model=InventoryChange)
def restore_remnant(request: Request, remnant_id: str, body: ReleaseRequest):
    return _run(request, lambda s: s.restore(remnant_id, body), write=True)


@router.post("/remnants/{remnant_id}/reserve", response_model=InventoryChange)
def reserve_remnant(request: Request, remnant_id: str, body: ReserveRequest, idempotency_key: IdempotencyKey = None):
    return _run(request, lambda s: s.idempotent(
        body.dataset_id, "remnant.reserve", idempotency_key, {"remnant_id": remnant_id, **body.model_dump(mode="json")},
        lambda: s.reserve(remnant_id, body)), write=True)


@router.post("/remnants/{remnant_id}/consume", response_model=InventoryChange)
def consume_remnant(request: Request, remnant_id: str, body: ConsumeRequest, idempotency_key: IdempotencyKey = None):
    return _run(request, lambda s: s.idempotent(
        body.dataset_id, "remnant.consume", idempotency_key, {"remnant_id": remnant_id, **body.model_dump(mode="json")},
        lambda: s.consume(remnant_id, body)), write=True)


@router.post("/remnants/{remnant_id}/release", response_model=InventoryChange)
def release_remnant(request: Request, remnant_id: str, body: ReleaseRequest, idempotency_key: IdempotencyKey = None):
    return _run(request, lambda s: s.idempotent(
        body.dataset_id, "remnant.release", idempotency_key, {"remnant_id": remnant_id, **body.model_dump(mode="json")},
        lambda: s.release_remnant(remnant_id, body)), write=True)


@router.post("/reservations/{reservation_id}/release", response_model=InventoryChange)
def release_reservation(request: Request, reservation_id: str, body: ReleaseRequest,
                        idempotency_key: IdempotencyKey = None):
    return _run(request, lambda s: s.idempotent(
        body.dataset_id, "reservation.release", idempotency_key,
        {"reservation_id": reservation_id, **body.model_dump(mode="json")},
        lambda: s.release_reservation(reservation_id, body)), write=True)


@router.post("/remnants/{remnant_id}/children", response_model=InventoryChange)
def add_children(request: Request, remnant_id: str, body: ChildRemnantsRequest):
    return _run(request, lambda s: s.add_children(remnant_id, body), write=True)


@router.get("/cutting/events", response_model=list[AuditEvent])
def cutting_events(request: Request, dataset_id: str, object_id: str | None = None,
                   after_seq: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=1000)] = 200):
    return _run(request, lambda s: s.events(dataset_id, object_id=object_id, after_seq=after_seq, limit=limit),
                write=False)


# ------------------------------------------------------------------------------------------ cutting
@router.post("/cutting/candidates", response_model=Candidates)
def find_candidates(request: Request, body: FindRequest):
    return _run(request, lambda s: s.find_candidates(body), write=False)


@router.post("/cutting/solve-input", response_model=SolveInput)
def solve_input(request: Request, body: SolveRequest):
    """The exact serialisable snapshot a solve job would receive (for the platform worker and audits)."""
    return _run(request, lambda s: s.solve_input(body), write=False)


@router.post("/cutting/solve", response_model=Job, status_code=202)
def solve(request: Request, body: SolveRequest):
    correlation_id = str(uuid.uuid4())
    submitter: JobSubmitter | None = getattr(request.app.state, "job_submitter", None)
    if submitter is None:
        return _error(CuttingError(503, "JOB_PLATFORM_UNAVAILABLE",
                                   "Платформа фоновых заданий не подключена; расчет не запущен.", retryable=True),
                      correlation_id)
    snapshot = _run(request, lambda s: s.solve_input(body), write=False)  # short read, closed before the job
    if isinstance(snapshot, JSONResponse):
        return snapshot
    job = submitter.submit("cutting.solve", body.dataset_id, snapshot.model_dump(mode="json"))
    return JSONResponse(status_code=202, content=job.model_dump(mode="json"))


@router.post("/cutting/impact", response_model=ImpactReport)
def impact(request: Request, body: ImpactRequest):
    return _run(request, lambda s: s.impact(body), write=False)


# ------------------------------------------------------------------------------------------ plans
@router.get("/plans", response_model=list[PlanSummary])
def list_plans(request: Request, dataset_id: str, limit: Annotated[int, Query(ge=1, le=200)] = 50):
    return _run(request, lambda s: s.list_plans(dataset_id, limit), write=False)


@router.get("/plans/active", response_model=CutPlan | None)
def active_plan(request: Request, dataset_id: str):
    return _run(request, lambda s: s.active_plan(dataset_id), write=False)


@router.post("/plans/compare", response_model=PlanComparison)
def compare_plans(request: Request, body: CompareRequest):
    return _run(request, lambda s: s.compare(body), write=False)


@router.get("/plans/{plan_id}", response_model=CutPlan)
def get_plan(request: Request, plan_id: str, dataset_id: str, revision: Annotated[int | None, Query(ge=0)] = None):
    return _run(request, lambda s: s.get_plan(dataset_id, plan_id, revision), write=False)


@router.get("/plans/{plan_id}/layout", response_model=PlanLayout)
def plan_layout(request: Request, plan_id: str, dataset_id: str, revision: Annotated[int | None, Query(ge=0)] = None):
    return _run(request, lambda s: s.layout(dataset_id, plan_id, revision), write=False)


@router.get("/plans/{plan_id}/export", response_model=SolutionExport)
def plan_export(request: Request, plan_id: str, dataset_id: str, revision: Annotated[int | None, Query(ge=0)] = None):
    return _run(request, lambda s: s.export(dataset_id, plan_id, revision), write=False)


@router.get("/plans/{plan_id}/free-remnants", response_model=FreeRemnantsCheck)
def plan_free_remnants(request: Request, plan_id: str, dataset_id: str,
                       revision: Annotated[int | None, Query(ge=0)] = None):
    """Live re-check of fully free original pieces (sale cards must call it right before create/confirm)."""
    return _run(request, lambda s: s.free_remnants(dataset_id, plan_id, revision), write=False)


@router.post("/plans/{plan_id}/draft", response_model=DraftResult)
def draft_plan(request: Request, plan_id: str, body: DraftRequest):
    return _run(request, lambda s: s.draft(plan_id, body), write=True)


@router.post("/plans/{plan_id}/validate", response_model=ValidationResult)
def validate_plan(request: Request, plan_id: str, dataset_id: str,
                  revision: Annotated[int | None, Query(ge=0)] = None):
    return _run(request, lambda s: s.validate(dataset_id, plan_id, revision), write=True)


@router.post("/plans/{plan_id}/commit", response_model=CommitResult)
def commit_plan(request: Request, plan_id: str, body: CommitPlan, idempotency_key: IdempotencyKey = None):
    return _run(request, lambda s: s.idempotent(
        body.dataset_id, "plan.commit", idempotency_key, {"plan_id": plan_id, **body.model_dump(mode="json")},
        lambda: s.commit(plan_id, body)), write=True)
