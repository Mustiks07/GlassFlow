from fastapi import APIRouter, Header, Request

from glassflow.contracts.platform import Job
from glassflow.contracts.readiness import SaleReadinessRequest
from glassflow.core.uow import idempotent, write_transaction
from glassflow.modules.platform.runs import enqueue_sale_readiness

router = APIRouter(tags=["sales"])


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
