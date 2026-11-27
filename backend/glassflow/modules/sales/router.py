from fastapi import APIRouter

from glassflow.contracts.common import ApiError
from glassflow.contracts.crm import Buyer, CardsRequest, SaleCard
from glassflow.core.errors import FeatureUnavailable

router = APIRouter(tags=["sales"], responses={501: {"model": ApiError}})


@router.get("/buyers", response_model=list[Buyer])
def list_buyers():
    raise FeatureUnavailable("sales.list_buyers")


@router.post("/sale-cards", response_model=list[SaleCard])
def create_cards(request: CardsRequest):
    raise FeatureUnavailable("sales.create_cards")
