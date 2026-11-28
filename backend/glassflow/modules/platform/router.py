from typing import Annotated

from fastapi import APIRouter, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from glassflow.contracts.common import ApiError
from glassflow.contracts.platform import (
    AISettings,
    Dataset,
    ExportResult,
    ImportCommit,
    ImportPreview,
    Job,
    KbHead,
    LocalSession,
    RestoreRequest,
    RunBudgetRenew,
    RunRequest,
    RunView,
    SettingsUpdate,
    WorkingCopy,
)
from glassflow.core.errors import AppError
from glassflow.core.models import DatasetRow
from glassflow.core.security import require_owner
from glassflow.core.uow import idempotent, write_transaction
from glassflow.modules.platform.imports import LIMIT, commit, dataset, dataset_dto, preview, working_copy
from glassflow.modules.platform.labor_router import router as labor_router

router = APIRouter(
    tags=["platform"],
    responses={
        400: {"model": ApiError},
        404: {"model": ApiError},
        409: {"model": ApiError},
        503: {"model": ApiError},
    },
)
router.include_router(labor_router)


@router.get("/session", response_model=LocalSession)
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
        from glassflow.modules.platform.imports import runtime_file_allowed

        if not (upload.filename or "").lower().endswith(".zip") and not runtime_file_allowed(
            upload.filename or ""
        ):
            content.append((upload.filename or "", b""))
            await upload.close()
            continue
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


@router.get("/datasets/{dataset_id}/kb", response_model=KbHead)
def current_kb(dataset_id: str, request: Request):
    from glassflow.modules.platform.kb import kb_head

    with request.app.state.session_factory() as session:
        return kb_head(session, dataset_id)


@router.post("/datasets/{dataset_id}/kb", response_model=KbHead)
async def update_kb(
    dataset_id: str,
    request: Request,
    file: UploadFile = File(...),
    expected_version: int = Form(..., ge=0),
    idempotency_key: str | None = Header(None),
):
    import hashlib

    from glassflow.modules.platform.imports import runtime_file_allowed
    from glassflow.modules.platform.kb import revise_kb

    filename = file.filename or ""
    if not filename.lower().endswith(".json") or not runtime_file_allowed(filename):
        raise AppError(422, "KB_INVALID", "Выберите runtime KB JSON.")
    content = await file.read(5_000_001)
    if len(content) > 5_000_000:
        raise AppError(413, "KB_TOO_LARGE", "KB превышает лимит 5 МБ.")
    body = {"sha256": hashlib.sha256(content).hexdigest(), "expected_version": expected_version}
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(
            session,
            dataset_id,
            "kb.revise",
            idempotency_key,
            body,
            lambda: revise_kb(
                session, dataset_id, content, filename, expected_version, request.state.correlation_id
            ),
        )


@router.post("/system/owner-check")
def owner_check(request: Request):
    require_owner(request)
    return {"authorized": True}


@router.post("/runs", response_model=Job, status_code=202)
def create_run(body: RunRequest, request: Request, idempotency_key: str | None = Header(None)):
    from glassflow.modules.platform.runs import create_run as start
    request.app.state.coordinator.configure_export_context(request.app.state.data_dir, request.app.state.services)

    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(
            session,
            body.dataset_id,
            "run.create",
            idempotency_key,
            body.model_dump(),
            lambda: start(session, body, request.app.state.services, request.state.correlation_id),
        )


@router.get("/runs/{run_id}", response_model=RunView)
def get_run(run_id: str, request: Request):
    from glassflow.modules.platform.runs import run_view

    with request.app.state.session_factory() as session:
        return run_view(session, run_id)


@router.post("/runs/{run_id}/budget", response_model=RunView)
def renew_run_budget(run_id: str, body: RunBudgetRenew, request: Request,
                     idempotency_key: str | None = Header(None)):
    from glassflow.modules.platform.runs import renew_budget
    request.app.state.coordinator.configure_export_context(request.app.state.data_dir, request.app.state.services)
    with write_transaction(request.app.state.session_factory) as session:
        return idempotent(session, body.dataset_id, f"run.budget:{run_id}", idempotency_key, body.model_dump(),
                          lambda: renew_budget(session, run_id, body, request.state.correlation_id))


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: str, request: Request, dataset_id: str | None = None):
    from glassflow.core.jobs import get_job, job_dto

    with request.app.state.session_factory() as session:
        return job_dto(get_job(session, job_id, dataset_id))


@router.post("/jobs/{job_id}/cancel", response_model=Job)
def cancel_job(job_id: str, request: Request, dataset_id: str):
    from glassflow.core.jobs import get_job, job_dto

    with write_transaction(request.app.state.session_factory) as session:
        row = get_job(session, job_id, dataset_id)
        if row.state in {"queued", "running"}:
            row.cancel_requested = True
        return job_dto(row)


@router.post("/runs/{run_id}/export", response_model=ExportResult)
def export_run(run_id: str, request: Request, idempotency_key: str | None = Header(None)):
    import threading

    from glassflow.core.models import IdempotencyRow
    from glassflow.core.uow import canonical_hash
    from glassflow.modules.platform.exports import export_run as execute
    from glassflow.modules.platform.runs import find_run

    # A local process owns this DB; serialize only exports, keeping solver/HTTP responsive.
    if not hasattr(request.app.state, "export_lock"):
        request.app.state.export_lock = threading.Lock()
    with request.app.state.export_lock:
        with request.app.state.session_factory() as session:
            run = find_run(session, run_id)
            dataset_id = run.dataset_id
            operation = f"run.export:{run_id}"
            if not idempotency_key or len(idempotency_key) > 128:
                raise AppError(422, "IDEMPOTENCY_KEY_REQUIRED", "Нужен Idempotency-Key.")
            previous = session.get(IdempotencyRow, (dataset_id, operation, idempotency_key))
            if previous:
                if previous.request_hash != canonical_hash({}):
                    raise AppError(409, "IDEMPOTENCY_CONFLICT", "Ключ использован другим запросом.")
                return previous.result
        result = execute(
            request.app.state.session_factory,
            run_id,
            request.app.state.data_dir,
            request.app.state.services,
            request.state.correlation_id,
        )
        with write_transaction(request.app.state.session_factory) as session:
            return idempotent(session, dataset_id, operation, idempotency_key, {}, lambda: result)


@router.get("/runs/{run_id}/files/{export_id}/{filename}")
def download_export(run_id: str, export_id: str, filename: str, request: Request):
    from uuid import UUID

    from glassflow.modules.platform.exports import SCHEMAS
    from glassflow.modules.platform.runs import find_run

    try:
        if str(UUID(export_id)) != export_id:
            raise ValueError()
    except ValueError:
        raise AppError(404, "EXPORT_NOT_FOUND", "Экспорт не найден.") from None
    if filename not in {*SCHEMAS, "manifest.json"}:
        raise AppError(404, "FILE_NOT_FOUND", "Файл не найден.")
    with request.app.state.session_factory() as session:
        find_run(session, run_id)
    path = request.app.state.data_dir / "exports" / run_id / export_id / filename
    if not path.is_file():
        raise AppError(404, "FILE_NOT_FOUND", "Файл не найден.")
    return FileResponse(
        path,
        filename=filename,
        media_type="text/csv; charset=utf-8" if filename.endswith(".csv") else "application/json",
    )


@router.get("/settings", response_model=AISettings)
def settings(request: Request):
    from glassflow.modules.platform.system import get_settings

    with request.app.state.session_factory() as session:
        return get_settings(session, request.app.state.secrets)


@router.post("/jobs/{job_id}/retry", response_model=Job, status_code=202)
def retry_job(job_id: str, dataset_id: str, request: Request, idempotency_key: str | None = Header(None)):
    from glassflow.core.jobs import enqueue, get_job, job_dto
    from glassflow.core.uow import get_object
    from glassflow.modules.platform.budgets import require_work_time
    from glassflow.modules.platform.runs import latest_jobs
    request.app.state.coordinator.configure_export_context(request.app.state.data_dir, request.app.state.services)

    with write_transaction(request.app.state.session_factory) as session:

        def action():
            original = get_job(session, job_id, dataset_id)
            if original.state not in {"failed", "cancelled", "interrupted"}:
                raise AppError(
                    409, "JOB_NOT_RETRYABLE", "Повтор доступен только после сбоя, отмены или прерывания."
                )
            snapshot = dict(original.input)
            if original.run_id:
                current_run = get_object(session, dataset_id, "run", original.run_id)
                budget = current_run.data.get("budget")
                require_work_time(budget)
                if budget:
                    snapshot["run_budget"] = budget
                    if original.kind == "cutting":
                        from glassflow.modules.platform.budgets import bound_solver
                        selected = latest_jobs(session, original.run_id).get("cutting")
                        if selected and selected.state == "completed":
                            snapshot["phase"] = "improvement"
                            snapshot["baseline_metrics"] = selected.result.get("metrics", {})
                        solver = bound_solver(budget["requested_solver"], budget,
                                              baseline=snapshot.get("phase") != "improvement")
                        snapshot["solver_config"] = solver
                        snapshot["cutting_snapshot"] = {**snapshot["cutting_snapshot"], "config": solver}
            if original.kind == "cards" and original.run_id:
                cutting = latest_jobs(session, original.run_id).get("cutting")
                if not cutting or cutting.state != "completed":
                    raise AppError(409, "CUTTING_NOT_COMPLETED", "Сначала завершите финальный раскрой.")
                snapshot["cutting_result"] = cutting.result
            snapshot["retry_of"] = job_id
            created = enqueue(session, dataset_id, original.kind, snapshot, original.run_id)
            session.flush()
            return job_dto(created).model_dump()

        return idempotent(session, dataset_id, f"job.retry:{job_id}", idempotency_key, {}, action)


@router.patch("/settings", response_model=AISettings)
def update_settings(body: SettingsUpdate, request: Request):
    from glassflow.modules.platform.system import save_settings

    require_owner(request)
    with write_transaction(request.app.state.session_factory) as session:
        result = save_settings(session, body, request.app.state.secrets)
    if body.api_key is not None:
        key = f"{body.profile}:{body.provider}"
        if body.api_key:
            request.app.state.secrets[key] = body.api_key
        else:
            request.app.state.secrets.pop(key, None)
    return result


@router.post("/settings/ai/check")
async def check_ai(request: Request):
    import asyncio

    from glassflow.modules.platform.system import get_settings

    require_owner(request)
    with request.app.state.session_factory() as session:
        settings = get_settings(session, request.app.state.secrets)
    checker = request.app.state.services.ai_check
    if checker is None:
        raise AppError(
            503,
            "AI_ADAPTER_UNAVAILABLE",
            "Проверка AI-провайдера пока не подключена; локальное ядро доступно.",
        )
    secret = request.app.state.secrets.get(f"{settings.profile}:{settings.provider}")
    try:
        operation = (
            checker(settings, secret)
            if asyncio.iscoroutinefunction(checker)
            else asyncio.to_thread(checker, settings, secret)
        )
        result = await asyncio.wait_for(operation, timeout=settings.timeout_seconds)
        return {
            k: result[k]
            for k in ("available", "provider", "model_id", "capabilities", "checked_at")
            if k in result
        }
    except Exception:
        raise AppError(
            503, "AI_CONNECTION_FAILED", "AI-профиль не прошел проверку подключения.", retryable=True
        ) from None


@router.post("/system/backup")
def backup(request: Request):
    from glassflow.modules.platform.system import create_backup

    require_owner(request)
    return create_backup(request.app.state.data_dir)


@router.get("/system/backups")
def list_backups(request: Request):
    import hashlib
    from datetime import UTC, datetime

    from glassflow.modules.platform.system import backup_path
    result = []
    for file in (request.app.state.data_dir / "backups").glob("*.db"):
        path = backup_path(request.app.state.data_dir, file.stem)
        result.append({"backup_id": path.stem, "created_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size})
    return sorted(result, key=lambda item: item["created_at"], reverse=True)


@router.get("/system/journal")
def journal(request: Request, limit: int = Query(50, ge=1, le=200)):
    from glassflow.core.models import AuditRow
    with request.app.state.session_factory() as session:
        return [{"at": row.created_at, "level": "info", "event": row.action,
                 "detail": row.object_id, "correlation_id": row.correlation_id}
                for row in session.scalars(select(AuditRow).order_by(AuditRow.id.desc()).limit(limit))]


@router.post("/system/restore")
def restore(body: RestoreRequest, request: Request):
    from glassflow.modules.platform.system import request_restore

    require_owner(request)
    request.app.state.coordinator.stop()
    try:
        result = request_restore(request.app.state.data_dir, body)
    except BaseException:
        from glassflow.core.jobs import Coordinator

        coordinator = request.app.state.coordinator
        replacement = Coordinator(
            request.app.state.session_factory,
            coordinator.handlers,
            tick=coordinator.tick,
            result_hooks=coordinator.result_hooks,
            private_context=coordinator.private_context,
            export_context=coordinator.export_context,
        )
        request.app.state.coordinator = replacement
        replacement.start()
        raise
    request.app.state.maintenance = True
    return result


@router.post("/datasets/demo", response_model=Dataset)
def import_demo(request: Request, idempotency_key: str | None = Header(None)):
    from pathlib import Path

    from glassflow.core.resources import resource_root

    names = [
        "1_ostatki/materials.csv",
        "1_ostatki/stock_open.csv",
        "1_ostatki/orders_open.csv",
        "2_assistant_crm/ksm_knowledge_base.json",
        "2_assistant_crm/applications_open.csv",
        "2_assistant_crm/questions_open.csv",
        "2_assistant_crm/dialogs_open.csv",
    ]
    files = [
        (Path(name).name, (resource_root() / "inputs/PACK_for_teams" / name).read_bytes()) for name in names
    ]
    with write_transaction(request.app.state.session_factory) as session:

        def action():
            report = preview(session, files)
            session.flush()
            return commit(
                session,
                report["import_id"],
                ImportCommit(name="Открытый учебный демонабор"),
                request.app.state.services,
                request.state.correlation_id,
            )

        return idempotent(session, "builtin:open-pack", "dataset.demo", idempotency_key, {}, action)


@router.post("/system/shutdown")
def shutdown(request: Request):
    from fastapi.responses import JSONResponse
    from starlette.background import BackgroundTask

    require_owner(request)
    request.app.state.coordinator.stop()
    callback = getattr(request.app.state, "shutdown_callback", None)
    return JSONResponse(
        {"status": "stopping" if callback else "worker_stopped", "restart_required": True},
        background=BackgroundTask(callback) if callback else None,
    )
