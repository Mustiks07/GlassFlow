from typing import Literal

from fastapi import APIRouter, Header, Request

from glassflow.contracts.labor import (
    LaborStudyCreate,
    LaborStudyExport,
    LaborStudyView,
    MeasurementAction,
    MeasurementAttest,
    MeasurementFinish,
    MeasurementStart,
    WorkflowQueue,
)
from glassflow.core.uow import get_object, idempotent, write_transaction
from glassflow.modules.platform import labor, workflow

router = APIRouter(tags=["labor-and-workflow"])


@router.post("/labor-studies", response_model=LaborStudyView)
def create_study(body: LaborStudyCreate, request: Request, idempotency_key: str | None = Header(None)):
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(session, body.dataset_id, "labor.create", idempotency_key, body.model_dump(),
            lambda: labor.create(session, body, request.state.correlation_id))


@router.get("/labor-studies", response_model=list[LaborStudyView])
def list_studies(dataset_id: str, request: Request):
    with request.app.state.session_factory() as session:
        return labor.list_studies(session, dataset_id)


@router.get("/labor-studies/{study_id}", response_model=LaborStudyView)
def get_study(study_id: str, dataset_id: str, request: Request):
    with request.app.state.session_factory() as session:
        return labor.view(get_object(session, dataset_id, "labor_study", study_id))


@router.get("/labor-studies/{study_id}/export", response_model=LaborStudyExport)
def export_study(study_id: str, dataset_id: str, request: Request):
    with request.app.state.session_factory() as session:
        return labor.export(session, dataset_id, study_id)


@router.post("/labor-studies/{study_id}/measurements", response_model=LaborStudyView)
def start_measurement(study_id: str, body: MeasurementStart, request: Request,
                      idempotency_key: str | None = Header(None)):
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(session, body.dataset_id, f"labor.start:{study_id}", idempotency_key, body.model_dump(),
            lambda: labor.start(session, study_id, body, request.state.correlation_id))


def mutate(study_id, measurement_id, body, request, key, action):
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(session, body.dataset_id, f"labor.{action}:{study_id}:{measurement_id}", key,
            body.model_dump(), lambda: labor.act(session, study_id, measurement_id, body, action,
                                                 request.state.correlation_id))


@router.post("/labor-studies/{study_id}/measurements/{measurement_id}/finish", response_model=LaborStudyView)
def finish_measurement(study_id: str, measurement_id: str, body: MeasurementFinish, request: Request,
                       idempotency_key: str | None = Header(None)):
    return mutate(study_id, measurement_id, body, request, idempotency_key, "finish")


@router.post("/labor-studies/{study_id}/measurements/{measurement_id}/attest", response_model=LaborStudyView)
def attest_measurement(study_id: str, measurement_id: str, body: MeasurementAttest, request: Request,
                       idempotency_key: str | None = Header(None)):
    return mutate(study_id, measurement_id, body, request, idempotency_key, "attest")


@router.post("/labor-studies/{study_id}/measurements/{measurement_id}/{action}", response_model=LaborStudyView)
def pause_resume(study_id: str, measurement_id: str, action: Literal["pause", "resume"],
                 body: MeasurementAction, request: Request, idempotency_key: str | None = Header(None)):
    return mutate(study_id, measurement_id, body, request, idempotency_key, action)


@router.get("/workflow/queue", response_model=WorkflowQueue)
def workflow_queue(dataset_id: str, request: Request):
    with request.app.state.session_factory() as session:
        return workflow.queue(session, dataset_id, request.app.state.services)
