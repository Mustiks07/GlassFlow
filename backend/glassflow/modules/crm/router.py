from fastapi import APIRouter, Header, Query, Request
from sqlalchemy import select

from glassflow.contracts.common import ApiError
from glassflow.contracts.crm import (
    ManagerMetrics,
    Ranking,
    RankRequest,
    Reminder,
    ReminderRequest,
    ReminderUpdate,
)
from glassflow.contracts.platform import VersionAction
from glassflow.core.errors import AppError
from glassflow.core.models import ObjectRow
from glassflow.core.uow import get_object, idempotent, write_transaction
from glassflow.modules.crm import service
from glassflow.modules.platform.imports import dataset, records

router = APIRouter(tags=["crm"], responses={404: {"model": ApiError}, 409: {"model": ApiError}})


@router.post("/crm/rank", response_model=Ranking)
def rank_applications(body: RankRequest, request: Request):
    with request.app.state.session_factory() as session:
        return service.rank(session, body.dataset_id, body.policy)


@router.get("/crm/applications")
def applications(
    dataset_id: str,
    request: Request,
    client_id: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    with request.app.state.session_factory() as session:
        rows = records(session, dataset_id, "applications")
        if client_id is not None:
            rows = [r for r in rows if r.data["client_id"] == client_id]
        return {
            "total": len(rows),
            "offset": offset,
            "rows": [{"source_row": r.source_row, **r.data} for r in rows[offset : offset + limit]],
        }


@router.get("/crm/reminders", response_model=list[Reminder])
def list_reminders(
    dataset_id: str, request: Request, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)
):
    with write_transaction(request.app.state.session_factory) as session:
        dataset(session, dataset_id)
        rows = session.scalars(
            select(ObjectRow)
            .where(ObjectRow.dataset_id == dataset_id, ObjectRow.kind == "reminder")
            .order_by(ObjectRow.id)
            .offset(offset)
            .limit(limit)
        ).all()
        for row in rows:
            service.refresh_reminder(session, row, request.app.state.services, request.state.correlation_id)
        return [service.reminder_dto(r) for r in rows]


@router.post("/crm/reminders", response_model=Reminder)
def create_reminder(body: ReminderRequest, request: Request, idempotency_key: str | None = Header(None)):
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(
            session,
            body.dataset_id,
            "reminder.create",
            idempotency_key,
            body.model_dump(),
            lambda: service.create_reminder(
                session, body, request.app.state.services, request.state.correlation_id
            ),
        )


@router.get("/crm/reminders/{reminder_id}", response_model=Reminder)
def get_reminder(reminder_id: str, dataset_id: str, request: Request):
    with write_transaction(request.app.state.session_factory) as session:
        row = get_object(session, dataset_id, "reminder", reminder_id)
        service.refresh_reminder(session, row, request.app.state.services, request.state.correlation_id)
        return service.reminder_dto(row)


def mutate(reminder_id, body, request, key, action):
    with write_transaction(request.app.state.session_factory) as session:
        result = idempotent(
            session,
            body.dataset_id,
            f"reminder.{action}:{reminder_id}",
            key,
            body.model_dump(),
            lambda: service.mutate_reminder(
                session, reminder_id, body, request.app.state.services, request.state.correlation_id, action
            ),
        )
    if "_conflict" in result:
        raise AppError(
            409,
            result["_conflict"],
            "Предмет устарел; закройте задачу или создайте новую.",
            conflicts=[reminder_id],
        )
    return result


@router.patch("/crm/reminders/{reminder_id}", response_model=Reminder)
def update_reminder(
    reminder_id: str, body: ReminderUpdate, request: Request, idempotency_key: str | None = Header(None)
):
    return mutate(reminder_id, body, request, idempotency_key, "update")


@router.post("/crm/reminders/{reminder_id}/confirm", response_model=Reminder)
def confirm_reminder(
    reminder_id: str, body: VersionAction, request: Request, idempotency_key: str | None = Header(None)
):
    return mutate(reminder_id, body, request, idempotency_key, "confirm")


@router.post("/crm/reminders/{reminder_id}/cancel", response_model=Reminder)
def cancel_reminder(
    reminder_id: str, body: VersionAction, request: Request, idempotency_key: str | None = Header(None)
):
    return mutate(reminder_id, body, request, idempotency_key, "cancel")


@router.get("/analytics/managers", response_model=list[ManagerMetrics])
def manager_metrics(
    dataset_id: str,
    request: Request,
    manager: str | None = None,
    product_group: str | None = None,
    channel: str | None = None,
    client_type: str | None = None,
    day_from: int | None = Query(None, ge=0),
    day_to: int | None = Query(None, ge=0),
):
    if manager and manager not in {"M1", "M2", "M3", "M4", "M5", "unknown"}:
        raise AppError(422, "INVALID_FILTER", "Выберите M1-M5 или unknown.")
    if day_from is not None and day_to is not None and day_from > day_to:
        raise AppError(422, "INVALID_RANGE", "Начало диапазона больше конца.")
    with request.app.state.session_factory() as session:
        return service.metrics(
            session,
            dataset_id,
            dict(
                manager=manager,
                product_group=product_group,
                channel=channel,
                client_type=client_type,
                day_from=day_from,
                day_to=day_to,
            ),
        )
