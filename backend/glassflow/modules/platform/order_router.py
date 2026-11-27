from typing import Literal

from fastapi import APIRouter, Header, Request
from sqlalchemy import select

from glassflow.contracts.orders import (
    OrderAction,
    OrderBind,
    OrderCreate,
    OrderHistory,
    OrderReminderLink,
    OrderSheet,
)
from glassflow.core.errors import AppError
from glassflow.core.models import ObjectRow
from glassflow.core.uow import idempotent, write_transaction
from glassflow.modules.platform import orders
from glassflow.modules.platform.imports import dataset

router = APIRouter(prefix="/order-sheets", tags=["orders"])


@router.post("", response_model=OrderSheet)
def create(body: OrderCreate, request: Request, idempotency_key: str | None = Header(None)):
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(session, body.dataset_id, "order.create", idempotency_key, body.model_dump(),
                          lambda: orders.create(session, body, request.state.correlation_id).model_dump(mode="json"))


@router.get("", response_model=list[OrderSheet])
def listing(dataset_id: str, request: Request):
    with write_transaction(request.app.state.session_factory) as session:
        dataset(session, dataset_id)
        rows = list(session.scalars(select(ObjectRow).where(ObjectRow.dataset_id == dataset_id,
                                                            ObjectRow.kind == "order_sheet")))
        return [orders.recheck(session, OrderSheet.model_validate(r.data), request.app.state.services,
                               request.state.correlation_id) for r in rows]


@router.get("/{order_id}", response_model=OrderSheet)
def get(order_id: str, dataset_id: str, request: Request):
    with write_transaction(request.app.state.session_factory) as session:
        return orders.recheck(session, orders.load(session, dataset_id, order_id),
                               request.app.state.services, request.state.correlation_id)


@router.get("/{order_id}/history", response_model=list[OrderHistory])
def history(order_id: str, dataset_id: str, request: Request):
    with request.app.state.session_factory() as session:
        return orders.history(session, dataset_id, order_id)


def mutate(order_id, body, action, request, key):
    with write_transaction(request.app.state.session_factory) as session:
        result = idempotent(session, body.dataset_id, f"order.{action}:{order_id}", key,
                            body.model_dump(mode="json"),
                            lambda: orders.apply(session, order_id, body, action,
                                                  request.app.state.services, request.state.correlation_id))
    if result.get("conflict"):
        raise AppError(409, result["conflict"], "Лист устарел; перечитайте его и привяжите новые факты.",
                       conflicts=[f"order:{order_id}:{result['sheet']['version']}",
                                  *result["sheet"]["stale_conflicts"]])
    return result["sheet"]


@router.post("/{order_id}/bind", response_model=OrderSheet)
def bind(order_id: str, body: OrderBind, request: Request, idempotency_key: str | None = Header(None)):
    return mutate(order_id, body, "bind", request, idempotency_key)


@router.post("/{order_id}/reminder", response_model=OrderSheet)
def reminder(order_id: str, body: OrderReminderLink, request: Request, idempotency_key: str | None = Header(None)):
    return mutate(order_id, body, "reminder", request, idempotency_key)


@router.post("/{order_id}/{action}", response_model=OrderSheet)
def action(order_id: str, action: Literal["confirm", "reserve", "warehouse-check", "handover", "release", "cancel"],
           body: OrderAction, request: Request, idempotency_key: str | None = Header(None)):
    return mutate(order_id, body, action, request, idempotency_key)
