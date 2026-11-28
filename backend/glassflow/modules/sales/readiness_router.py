from fastapi import APIRouter, Header, Request

from glassflow.contracts.cutting import SaleReadiness
from glassflow.contracts.platform import Job
from glassflow.contracts.readiness import SaleReadinessRequest
from glassflow.core.errors import AppError
from glassflow.core.models import JobRow
from glassflow.core.uow import idempotent, write_transaction
from glassflow.modules.platform.runs import enqueue_sale_readiness

router = APIRouter(tags=["sales"])


@router.get("/sale-readiness/{job_id}", response_model=SaleReadiness)
def readiness_result(job_id: str, dataset_id: str, request: Request):
    with request.app.state.session_factory() as session:
        job = session.get(JobRow, job_id)
        if job is None or job.dataset_id != dataset_id or job.kind != "cutting":
            raise AppError(404, "READINESS_NOT_FOUND", "Совместная проверка не найдена.")
        if job.state != "completed" or not (job.result or {}).get("sale_readiness"):
            raise AppError(409, "READINESS_NOT_READY", "Совместная проверка ещё не принята.")
        return job.result["sale_readiness"]


@router.post("/sale-readiness", response_model=Job, status_code=202)
def sale_readiness(body: SaleReadinessRequest, request: Request, idempotency_key: str | None = Header(None)):
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(
            session,
            body.dataset_id,
            "sale_readiness",
            idempotency_key,
            body.model_dump(),
            lambda: enqueue_sale_readiness(
                session,
                body.dataset_id,
                body.plan_id,
                body.revision,
                body.buyer_registry_version,
                budget_seconds=body.budget_seconds,
            ),
        )
