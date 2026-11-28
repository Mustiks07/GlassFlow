from fastapi import APIRouter, File, Header, Query, Request, UploadFile
from sqlalchemy import select

from glassflow.contracts.common import ApiError
from glassflow.contracts.crm import Buyer, BuyerMatch, CardsRequest, CardUpdate, SaleCard
from glassflow.core.errors import AppError
from glassflow.core.models import ObjectRow
from glassflow.core.uow import get_object, idempotent, write_transaction
from glassflow.modules.platform.imports import dataset, records
from glassflow.modules.sales import service

router = APIRouter(
    tags=["sales"], responses={404: {"model": ApiError}, 409: {"model": ApiError}, 503: {"model": ApiError}}
)


@router.get("/buyers", response_model=list[Buyer])
def list_buyers(
    dataset_id: str,
    version: str,
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    with request.app.state.session_factory() as session:
        return service.registry(session, dataset_id, version, False).data["buyers"][offset : offset + limit]


@router.get("/buyers/registries")
def registries(dataset_id: str, request: Request):
    with request.app.state.session_factory() as session:
        dataset(session, dataset_id)
        return [
            {"version": r.id, **{k: v for k, v in r.data.items() if k not in {"buyers", "evidence"}}}
            for r in session.scalars(
                select(ObjectRow).where(
                    ObjectRow.dataset_id == dataset_id, ObjectRow.kind == "buyer_registry"
                )
            )
        ]


@router.get("/buyers/matches", response_model=list[BuyerMatch])
def matches(dataset_id: str, version: str, remnant_id: str, request: Request):
    with request.app.state.session_factory() as session:
        return service.current_matches(session, dataset_id, version, remnant_id, request.app.state.services)


@router.post("/buyers/import")
async def import_buyers(
    dataset_id: str,
    request: Request,
    file: UploadFile = File(...),
    evidence: UploadFile = File(...),
    idempotency_key: str | None = Header(None),
):
    content, proof = await file.read(2_000_001), await evidence.read(2_000_001)
    if len(content) > 2_000_000 or len(proof) > 2_000_000:
        raise AppError(413, "BUYERS_TOO_LARGE", "Реестр/evidence превышает лимит 2 МБ.")
    import hashlib

    body = {"csv": hashlib.sha256(content).hexdigest(), "evidence": hashlib.sha256(proof).hexdigest()}
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(
            session,
            dataset_id,
            "buyers.import",
            idempotency_key,
            body,
            lambda: service.import_buyers(session, dataset_id, content, proof, request.state.correlation_id),
        )


@router.post("/sale-cards", response_model=list[SaleCard])
def create_cards(body: CardsRequest, request: Request, idempotency_key: str | None = Header(None)):
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(
            session,
            body.dataset_id,
            "cards.generate",
            idempotency_key,
            body.model_dump(),
            lambda: service.generate_cards(
                session, body, request.app.state.services, request.state.correlation_id
            ),
        )["cards"]


@router.get("/sale-cards", response_model=list[SaleCard])
def list_cards(dataset_id: str, request: Request, plan_id: str | None = None):
    with write_transaction(request.app.state.session_factory) as session:
        return service.list_cards(
            session, dataset_id, request.app.state.services, request.state.correlation_id, plan_id
        )


@router.post("/sale-cards/{card_id}/recheck", response_model=SaleCard)
def recheck(card_id: str, dataset_id: str, request: Request):
    with write_transaction(request.app.state.session_factory) as session:
        row = get_object(session, dataset_id, "sale_card", card_id)
        return service.recheck_card(session, row, request.app.state.services, request.state.correlation_id)


@router.patch("/sale-cards/{card_id}", response_model=SaleCard)
def edit_card(card_id: str, body: CardUpdate, request: Request, idempotency_key: str | None = Header(None)):
    def action(session):
        row = get_object(session, body.dataset_id, "sale_card", card_id, body.expected_version)
        card = service.recheck_card(session, row, request.app.state.services, request.state.correlation_id)
        if card.status == "stale":
            return {"_conflict": True}
        if body.factor is not None:
            original = next(
                r.data for r in records(session, body.dataset_id, "stock") if r.public_id == card.remnant_id
            )
            material = next(
                r.data
                for r in records(session, body.dataset_id, "materials")
                if r.public_id == original["material_id"]
            )
            card.price_tg = service.card_price(
                int(original["длина_мм"]),
                int(original["ширина_мм"]),
                material["цена_нового_стекла_тг_за_м2"],
                body.factor,
            )
            card.factor = body.factor
        if body.top3_buyer_ids is not None:
            buyers = {m.buyer_id: m for m in service.current_matches(session, body.dataset_id,
                      card.buyer_registry_version, card.remnant_id, request.app.state.services)}
            if len(set(body.top3_buyer_ids)) != 3 or any(b not in buyers for b in body.top3_buyer_ids):
                raise AppError(422, "INVALID_TOP3", "Выберите трех разных пригодных покупателей этого реестра.")
            card.top3_buyer_ids = body.top3_buyer_ids
            card.buyer_matches = [buyers[b] for b in body.top3_buyer_ids]
            card.top3_buyers = [buyers[b].name for b in body.top3_buyer_ids]
            card.target_buyer = card.top3_buyers[0]
        card.version += 1
        row.version, row.data = card.version, card.model_dump()
        return card.model_dump()

    with write_transaction(request.app.state.session_factory) as session:
        result = idempotent(
            session,
            body.dataset_id,
            f"card.edit:{card_id}",
            idempotency_key,
            body.model_dump(),
            lambda: action(session),
        )
    if result.get("_conflict"):
        raise AppError(409, "STALE_CARD", "Карточка устарела; создайте новую после пересчета.")
    return result
