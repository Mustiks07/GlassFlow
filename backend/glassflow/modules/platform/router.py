from typing import Annotated

from fastapi import APIRouter, File, Header, Query, Request, UploadFile
from sqlalchemy import select

from glassflow.contracts.common import ApiError
from glassflow.contracts.platform import Dataset, ImportCommit, ImportPreview, WorkingCopy
from glassflow.core.errors import AppError
from glassflow.core.models import DatasetRow
from glassflow.core.security import require_owner
from glassflow.core.uow import idempotent, write_transaction
from glassflow.modules.platform.imports import LIMIT, commit, dataset, dataset_dto, preview, working_copy

router = APIRouter(
    tags=["platform"],
    responses={
        400: {"model": ApiError},
        404: {"model": ApiError},
        409: {"model": ApiError},
        503: {"model": ApiError},
    },
)


@router.get("/session")
def local_session(request: Request):
    return {"session_token": request.app.state.local_token}


@router.get("/datasets", response_model=list[Dataset])
def list_datasets(request: Request, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    with request.app.state.session_factory() as session:
        return [
            dataset_dto(r)
            for r in session.scalars(
                select(DatasetRow).order_by(DatasetRow.created_at).offset(offset).limit(limit)
            )
        ]


@router.get("/datasets/{dataset_id}", response_model=Dataset)
def get_dataset(dataset_id: str, request: Request):
    with request.app.state.session_factory() as session:
        return dataset_dto(dataset(session, dataset_id))


@router.post("/imports/preview", response_model=ImportPreview)
async def preview_import(
    request: Request,
    file: Annotated[UploadFile | None, File()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
):
    uploads = ([file] if file else []) + (files or [])
    if not uploads or len(uploads) > 20:
        raise AppError(422, "FILES_REQUIRED", "Выберите ZIP или от одного до 20 файлов.")
    content, size = [], 0
    for upload in uploads:
        data = await upload.read(LIMIT + 1)
        size += len(data)
        if size > LIMIT:
            raise AppError(413, "IMPORT_TOO_LARGE", "Размер импорта превышает 50 МиБ.")
        content.append((upload.filename or "", data))
    with write_transaction(request.app.state.session_factory) as session:
        return preview(session, content)


@router.post("/imports/{import_id}/commit", response_model=Dataset)
def commit_import(
    import_id: str, body: ImportCommit, request: Request, idempotency_key: str | None = Header(None)
):
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(
            session,
            f"import:{import_id}",
            "import.commit",
            idempotency_key,
            body.model_dump(),
            lambda: commit(
                session, import_id, body, request.app.state.services, request.state.correlation_id
            ),
        )


@router.post("/datasets/{dataset_id}/working-copy", response_model=Dataset)
def create_working_copy(
    dataset_id: str, body: WorkingCopy, request: Request, idempotency_key: str | None = Header(None)
):
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(
            session,
            dataset_id,
            "dataset.copy",
            idempotency_key,
            body.model_dump(),
            lambda: working_copy(
                session, dataset_id, body.name, request.app.state.services, request.state.correlation_id
            ),
        )


@router.get("/datasets/{dataset_id}/sources/{kind}")
def source_manifest(dataset_id: str, kind: str, request: Request):
    from glassflow.core.models import SourceRow

    with request.app.state.session_factory() as session:
        dataset(session, dataset_id)
        row = session.scalar(
            select(SourceRow).where(SourceRow.dataset_id == dataset_id, SourceRow.kind == kind)
        )
        if row is None:
            raise AppError(404, "SOURCE_NOT_FOUND", "Исходный файл не найден.")
        return {
            "filename": row.filename,
            "sha256": row.sha256,
            "row_count": row.row_count,
            "schema_version": row.schema_version,
            "imported_at": row.imported_at,
        }


@router.post("/system/owner-check")
def owner_check(request: Request):
    require_owner(request)
    return {"authorized": True}
