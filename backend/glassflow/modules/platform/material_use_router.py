from fastapi import APIRouter, Header, Query, Request

from glassflow.contracts.material_use import (
    MaterialUseAssessment,
    MaterialUseRecord,
    MaterialUseRequest,
    MaterialUseSummary,
)
from glassflow.core.errors import AppError
from glassflow.core.models import MaterialUseRow
from glassflow.core.uow import idempotent, write_transaction
from glassflow.modules.platform import material_use

router = APIRouter(prefix="/material-use", tags=["material-use"])


@router.post("/preview", response_model=MaterialUseAssessment)
def preview(body: MaterialUseRequest, request: Request):
    with write_transaction(request.app.state.session_factory) as session:
        return material_use.preview(session, body, request.app.state.services)


@router.post("", response_model=MaterialUseRecord)
def confirm(body: MaterialUseRequest, request: Request, idempotency_key: str | None = Header(None)):
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(session, body.dataset_id, f"material_use:{body.subject_type}:{body.subject_id}",
            idempotency_key, body.model_dump(mode="json"),
            lambda: material_use.confirm(session, body, request.app.state.services, request.state.correlation_id))


@router.get("", response_model=list[MaterialUseRecord])
def listing(dataset_id: str, request: Request, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    with request.app.state.session_factory() as session:
        return material_use.listing(session, dataset_id, offset, limit)


@router.get("/summary", response_model=MaterialUseSummary)
def summary(dataset_id: str, request: Request):
    with request.app.state.session_factory() as session:
        return material_use.summary(session, dataset_id)


@router.get("/{usage_id}", response_model=MaterialUseRecord)
def get(usage_id: str, dataset_id: str, request: Request):
    with request.app.state.session_factory() as session:
        row = session.get(MaterialUseRow, usage_id)
        if row is None or row.dataset_id != dataset_id:
            raise AppError(404, "MATERIAL_USE_NOT_FOUND", "Подтверждение не найдено в этом наборе.")
        return MaterialUseRecord.model_validate(row.data)
