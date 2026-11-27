from typing import Literal

from fastapi import APIRouter, Header, Query, Request
from sqlalchemy import select

from glassflow.contracts.baskets import (
    Basket,
    BasketApplyParse,
    BasketBind,
    BasketCreate,
    BasketHistory,
    BasketLinesUpdate,
)
from glassflow.contracts.orders import OrderAction
from glassflow.contracts.platform import Job
from glassflow.core.errors import AppError
from glassflow.core.models import ObjectRow
from glassflow.core.uow import idempotent, write_transaction
from glassflow.modules.platform import baskets
from glassflow.modules.platform.imports import dataset

router = APIRouter(prefix="/baskets", tags=["baskets"])


@router.post("", response_model=Basket)
def create(body: BasketCreate, request: Request, idempotency_key: str | None = Header(None)):
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(session, body.dataset_id, "basket.create", idempotency_key, body.model_dump(mode="json"),
                           lambda: baskets.create(session, body, request.state.correlation_id).model_dump(mode="json"))


@router.get("", response_model=list[Basket])
def listing(dataset_id: str, request: Request, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    with write_transaction(request.app.state.session_factory) as session:
        dataset(session, dataset_id)
        rows = list(session.scalars(select(ObjectRow).where(ObjectRow.dataset_id == dataset_id,
                    ObjectRow.kind == "basket").order_by(ObjectRow.id).offset(offset).limit(limit)))
        return [baskets.recheck(session, Basket.model_validate(r.data), request.app.state.services,
                                 request.state.correlation_id) for r in rows]


@router.get("/{basket_id}", response_model=Basket)
def get(basket_id: str, dataset_id: str, request: Request):
    with write_transaction(request.app.state.session_factory) as session:
        return baskets.recheck(session, baskets.load(session, dataset_id, basket_id),
                                request.app.state.services, request.state.correlation_id)


@router.get("/{basket_id}/history", response_model=list[BasketHistory])
def history(basket_id: str, dataset_id: str, request: Request):
    with request.app.state.session_factory() as session:
        return baskets.history(session, dataset_id, basket_id)


def mutate(basket_id, body, action, request, key):
    with write_transaction(request.app.state.session_factory) as session:
        result = idempotent(session, body.dataset_id, f"basket.{action}:{basket_id}", key, body.model_dump(mode="json"),
                            lambda: baskets.apply(session, basket_id, body, action,
                                                   request.app.state.services, request.state.correlation_id))
    if result.get("conflict"):
        raise AppError(409, result["conflict"], "Корзина устарела; уточните все позиции и привяжите новые факты.",
                       conflicts=[f"basket:{basket_id}:{result['basket']['version']}"])
    return result["basket"]


@router.post("/{basket_id}/lines", response_model=Basket)
def lines(basket_id: str, body: BasketLinesUpdate, request: Request, idempotency_key: str | None = Header(None)):
    return mutate(basket_id, body, "lines", request, idempotency_key)


@router.post("/{basket_id}/bind", response_model=Basket)
def bind(basket_id: str, body: BasketBind, request: Request, idempotency_key: str | None = Header(None)):
    return mutate(basket_id, body, "bind", request, idempotency_key)


@router.post("/{basket_id}/parse", response_model=Job, status_code=202)
def parse(basket_id: str, body: OrderAction, request: Request, idempotency_key: str | None = Header(None)):
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(session, body.dataset_id, f"basket.parse:{basket_id}", idempotency_key, body.model_dump(mode="json"),
            lambda: baskets.parse_job(session, baskets.load(session, body.dataset_id, basket_id, body.expected_version),
                                      body, request.app.state.coordinator.handlers, request.state.correlation_id))


@router.post("/{basket_id}/apply-parse", response_model=Basket)
def apply_parse(basket_id: str, body: BasketApplyParse, request: Request, idempotency_key: str | None = Header(None)):
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(session, body.dataset_id, f"basket.apply_parse:{basket_id}", idempotency_key, body.model_dump(mode="json"),
            lambda: baskets.apply_parse(session, baskets.load(session, body.dataset_id, basket_id, body.expected_version),
                                          body, request.state.correlation_id).model_dump(mode="json"))


@router.post("/{basket_id}/{action}", response_model=Basket)
def action(basket_id: str, action: Literal["confirm", "reserve", "warehouse-check", "handover", "release", "cancel"],
           body: OrderAction, request: Request, idempotency_key: str | None = Header(None)):
    return mutate(basket_id, body, action, request, idempotency_key)
