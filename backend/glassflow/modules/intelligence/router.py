from fastapi import APIRouter

from glassflow.contracts.common import ApiError
from glassflow.contracts.intelligence import (
    AssistantReply,
    AssistantTurn,
    CatalogProduct,
    DialogRequest,
    DialogVerdict,
    Quote,
    QuoteRequest,
)
from glassflow.core.errors import FeatureUnavailable

router = APIRouter(tags=["intelligence"], responses={501: {"model": ApiError}})


@router.get("/catalog", response_model=list[CatalogProduct])
def list_catalog(dataset_id: str, kb_version: str):
    raise FeatureUnavailable("intelligence.list_catalog")


@router.post("/quotes", response_model=Quote)
def calculate_quote(request: QuoteRequest):
    raise FeatureUnavailable("intelligence.calculate_quote")


@router.get("/quotes/{quote_id}", response_model=Quote)
def get_quote(quote_id: str, dataset_id: str):
    raise FeatureUnavailable("intelligence.get_quote")


@router.post("/assistant/turns", response_model=AssistantReply)
def assistant_turn(request: AssistantTurn):
    raise FeatureUnavailable("intelligence.assistant_turn")


@router.post("/quality/check", response_model=DialogVerdict)
def check_dialog(request: DialogRequest):
    raise FeatureUnavailable("intelligence.check_dialog")
