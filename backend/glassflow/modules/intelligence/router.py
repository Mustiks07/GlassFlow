"""HTTP routes of the intelligence module (prefix /api/v1 added by the platform).

Composition: the platform may put a ready ``IntelligenceService`` on
``app.state.intelligence_service`` (real dataset sources, inventory/CRM ports, settings and
secret store). Until then the router builds one from the shared session factory, the
bootstrap open-pack sources and environment AI settings — clearly marked as bootstrap.
"""

from __future__ import annotations

from typing import Callable
from uuid import uuid4

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from glassflow.contracts.common import ApiError
from glassflow.contracts.intelligence import (
    AIProfileView,
    AnswerBatchRequest,
    AnswerBatchResult,
    AssistantReply,
    AssistantTurn,
    CatalogProduct,
    CatalogRule,
    CatalogSearchResult,
    Conversation,
    DialogBatchRequest,
    DialogBatchResult,
    DialogRequest,
    DialogVerdict,
    DimensionNormalizeRequest,
    DimensionNormalizeResult,
    MappingConfirmRequest,
    MaterialMapping,
    PriceVersion,
    Quote,
    QuoteCancelRequest,
    QuoteConfirmRequest,
    QuoteRequest,
    QuoteReviseRequest,
)

from .service import IntelligenceError, IntelligenceService

router = APIRouter(
    tags=["intelligence"],
    responses={404: {"model": ApiError}, 409: {"model": ApiError}, 422: {"model": ApiError}},
)


def build_default_service(app) -> IntelligenceService:
    from .assistant.prompts import PROMPT_VERSION
    from .providers.settings import EnvSecrets, build_runtime, profile_from_env
    from .service import DbLedger
    from .sources import PackDirectorySources, default_pack_dir

    session_factory = app.state.session_factory
    secrets = EnvSecrets()
    runtime = build_runtime(profile_from_env(secrets=secrets), secrets, prompt_version=PROMPT_VERSION, ledger=DbLedger(session_factory))
    return IntelligenceService(PackDirectorySources(default_pack_dir()), session_factory, runtime=runtime)


def service_for(request: Request) -> IntelligenceService:
    service = getattr(request.app.state, "intelligence_service", None)
    if service is None:
        service = build_default_service(request.app)
        request.app.state.intelligence_service = service
    return service


def _error(exc: IntelligenceError, correlation_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content=ApiError(
            code=exc.code,
            message_ru=exc.message_ru,
            field_errors=exc.field_errors,
            conflict_objects=exc.conflict_objects,
            retryable=exc.retryable,
            correlation_id=correlation_id,
        ).model_dump(),
    )


def _run(fn: Callable, *args, **kwargs):
    correlation_id = str(uuid4())
    try:
        return fn(*args, **kwargs)
    except IntelligenceError as exc:
        return _error(exc, correlation_id)


async def _run_async(fn, *args, **kwargs):
    correlation_id = str(uuid4())
    try:
        return await fn(*args, **kwargs)
    except IntelligenceError as exc:
        return _error(exc, correlation_id)


# ------------------------------------------------------------------ catalog
@router.get("/catalog", response_model=list[CatalogProduct])
def list_catalog(request: Request, dataset_id: str, kb_version: str | None = None, kind: str | None = None):
    return _run(service_for(request).list_catalog, dataset_id, kb_version, kind)


@router.get("/catalog/search", response_model=CatalogSearchResult)
def search_catalog(request: Request, dataset_id: str, q: str):
    return _run(service_for(request).search_catalog, dataset_id, q[:200])


@router.get("/catalog/versions", response_model=list[PriceVersion])
def price_versions(request: Request, dataset_id: str):
    return _run(service_for(request).price_versions, dataset_id)


@router.get("/catalog/rules", response_model=list[CatalogRule])
def list_rules(request: Request, dataset_id: str):
    return _run(service_for(request).list_rules, dataset_id)


@router.get("/catalog/mappings", response_model=list[MaterialMapping])
def list_mappings(request: Request, dataset_id: str):
    return _run(service_for(request).list_mappings, dataset_id)


@router.post("/catalog/mappings/{catalog_product_id}/confirm", response_model=MaterialMapping)
def confirm_mapping(request: Request, catalog_product_id: str, body: MappingConfirmRequest):
    return _run(service_for(request).confirm_mapping, catalog_product_id, body)


@router.get("/catalog/products/{catalog_product_id}", response_model=CatalogProduct)
def get_product(request: Request, catalog_product_id: str, dataset_id: str):
    return _run(service_for(request).get_product, dataset_id, catalog_product_id)


# ------------------------------------------------------------------ quotes
@router.post("/quotes", response_model=Quote)
def calculate_quote(request: Request, body: QuoteRequest):
    return _run(service_for(request).calculate_quote, body)


@router.post("/quotes/calculate", response_model=Quote)
def calculate_quote_alias(request: Request, body: QuoteRequest):
    return _run(service_for(request).calculate_quote, body)


@router.post("/quotes/dimensions/normalize", response_model=DimensionNormalizeResult)
def normalize_dimensions(body: DimensionNormalizeRequest):
    return IntelligenceService.normalize_dimensions(body.text)


@router.get("/quotes/{quote_id}", response_model=Quote)
def get_quote(request: Request, quote_id: str, dataset_id: str, revision: int | None = None):
    return _run(service_for(request).get_quote, quote_id, dataset_id, revision)


@router.get("/quotes/{quote_id}/revisions", response_model=list[Quote])
def list_quote_revisions(request: Request, quote_id: str, dataset_id: str):
    return _run(service_for(request).list_revisions, quote_id, dataset_id)


@router.post("/quotes/{quote_id}/revise", response_model=Quote)
def revise_quote(request: Request, quote_id: str, body: QuoteReviseRequest):
    return _run(service_for(request).revise_quote, quote_id, body)


@router.post("/quotes/{quote_id}/confirm", response_model=Quote)
def confirm_quote(
    request: Request, quote_id: str, body: QuoteConfirmRequest, idempotency_key: str | None = Header(default=None, max_length=128)
):
    return _run(service_for(request).confirm_quote, quote_id, body, idempotency_key)


@router.post("/quotes/{quote_id}/cancel", response_model=Quote)
def cancel_quote(request: Request, quote_id: str, body: QuoteCancelRequest):
    return _run(service_for(request).cancel_quote, quote_id, body)


# ------------------------------------------------------------------ assistant
@router.post("/assistant/turns", response_model=AssistantReply)
async def assistant_turn(request: Request, body: AssistantTurn):
    return await _run_async(service_for(request).assistant_turn, body, str(uuid4()))


@router.get("/assistant/conversations/{conversation_id}", response_model=Conversation)
def get_conversation(request: Request, conversation_id: str, dataset_id: str):
    return _run(service_for(request).get_conversation, conversation_id, dataset_id)


@router.post("/assistant/batch", response_model=AnswerBatchResult)
async def answer_batch(request: Request, body: AnswerBatchRequest):
    return await _run_async(service_for(request).answer_questions, body)


@router.get("/assistant/ai-status", response_model=AIProfileView)
def ai_status(request: Request):
    return service_for(request).ai_profile()


@router.get("/assistant/usage")
def ai_usage(request: Request, since: str | None = None):
    return service_for(request).usage_summary(since)


# ------------------------------------------------------------------ quality
@router.post("/quality/check", response_model=DialogVerdict)
def check_dialog(request: Request, body: DialogRequest):
    return _run(service_for(request).check_dialog_sync, body)


@router.post("/quality/batch", response_model=DialogBatchResult)
def check_dialogs(request: Request, body: DialogBatchRequest):
    return _run(service_for(request).check_dialogs, body)
