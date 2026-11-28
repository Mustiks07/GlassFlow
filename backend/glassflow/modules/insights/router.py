from typing import Literal

from fastapi import APIRouter, Header, Request, Response

from glassflow.contracts.insights import (
    AnalyticsAnswer,
    AnalyticsQuestion,
    ComparableRequest,
    ComparableView,
    PieceLabel,
    PieceLabelCreate,
    PieceLabelResolved,
    ResultPassport,
    WarehouseDocument,
    WarehouseDocumentCreate,
)
from glassflow.core.uow import idempotent, write_transaction

from . import comparable, documents, passports

router = APIRouter(tags=["insights"])


@router.get("/runs/{run_id}/passport", response_model=ResultPassport)
def result_passport(
    run_id: str, dataset_id: str, request: Request, view: Literal["current", "accepted"] = "current"
):
    with request.app.state.session_factory() as session:
        return passports.passport(session, request.app.state.data_dir, run_id, dataset_id, view)


@router.post("/analytics/comparable", response_model=ComparableView)
def compare_managers(body: ComparableRequest, request: Request):
    with request.app.state.session_factory() as session:
        return comparable.compare(session, body)


@router.post("/analytics/questions", response_model=AnalyticsAnswer)
def analytics_question(body: AnalyticsQuestion, request: Request):
    with request.app.state.session_factory() as session:
        return comparable.answer(session, body)


@router.post("/piece-labels", response_model=PieceLabel)
def create_label(body: PieceLabelCreate, request: Request, idempotency_key: str | None = Header(None)):
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(
            session,
            body.dataset_id,
            "piece_label.create",
            idempotency_key,
            body.model_dump(),
            lambda: documents.create_label(session, body, request.state.correlation_id),
        )


@router.get("/piece-labels/{label_id}", response_model=PieceLabel)
def piece_label(label_id: str, dataset_id: str, request: Request):
    with request.app.state.session_factory() as session:
        return documents.label(session, dataset_id, label_id)


@router.get("/piece-labels/{label_id}/resolve", response_model=PieceLabelResolved)
def resolve_label(label_id: str, dataset_id: str, request: Request):
    with request.app.state.session_factory() as session:
        return documents.resolve_label(session, dataset_id, label_id)


@router.get("/piece-labels/{label_id}/pdf", response_class=Response)
def piece_label_pdf(label_id: str, dataset_id: str, request: Request):
    with request.app.state.session_factory() as session:
        value = documents.label(session, dataset_id, label_id)
    return Response(
        documents.label_pdf(value),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="piece-{value.label_id}.pdf"'},
    )


@router.post("/warehouse-documents", response_model=WarehouseDocument)
def create_warehouse_document(
    body: WarehouseDocumentCreate, request: Request, idempotency_key: str | None = Header(None)
):
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(
            session,
            body.dataset_id,
            "warehouse_document.create",
            idempotency_key,
            body.model_dump(),
            lambda: documents.create_issue_sheet(
                session, body, request.app.state.services, request.state.correlation_id
            ),
        )


@router.get("/warehouse-documents/{document_id}", response_model=WarehouseDocument)
def warehouse_document(document_id: str, dataset_id: str, request: Request):
    with request.app.state.session_factory() as session:
        return documents.issue_sheet(session, dataset_id, document_id)


@router.get("/warehouse-documents/{document_id}/pdf", response_class=Response)
def warehouse_document_pdf(document_id: str, dataset_id: str, request: Request):
    with request.app.state.session_factory() as session:
        value = documents.issue_sheet(session, dataset_id, document_id)
    return Response(
        documents.issue_pdf(value),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="warehouse-{value.document_id}.pdf"'},
    )
