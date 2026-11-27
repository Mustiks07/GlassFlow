import importlib.metadata
import os
import platform

from sqlalchemy import select

from glassflow.core.errors import AppError
from glassflow.core.jobs import enqueue, job_dto
from glassflow.core.models import JobRow, ObjectRow, now, uid
from glassflow.core.uow import canonical_hash, get_object
from glassflow.modules.crm.service import rank_rows
from glassflow.modules.platform.imports import dataset, records, working_copy

MODULE_FILES = {"cutting": "solution.csv", "assistant": "answers.csv", "crm": "picks.csv",
                "quality": "verdicts.csv", "cards": "sale_cards.csv"}


def crm_job(snapshot, context):
    result = rank_rows(snapshot["applications"])
    context.progress("ranked", 25, 25)
    return {"rows": [{"app_id": r.app_id} for r in result.rows], "policy": result.policy_version,
            "observed_precision": result.observed_precision}


def create_run(session, request, services, correlation):
    if request.solver_config.workers > max(1, (os.cpu_count() or 1) - 1):
        raise AppError(422, "CPU_BUDGET_EXCEEDED", "Число потоков превышает CPU-1.")
    if request.solver_config.time_limit_seconds > 3600:
        raise AppError(422, "TIME_BUDGET_EXCEEDED", "Бюджет одного задания ограничен часом.")
    source = dataset(session, request.dataset_id)
    if source.mode == "workspace":
        raise AppError(409, "IMMUTABLE_SOURCE_REQUIRED", "Выберите исходный снимок для конкурсного прогона.")
    if not request.modules or len(set(request.modules)) != len(request.modules):
        raise AppError(422, "INVALID_MODULES", "Выберите неповторяющиеся модули.")
    copy = working_copy(session, source.id, f"Прогон: {source.name}", services, correlation, mode="contest")
    snapshot = dataset(session, copy["dataset_id"])
    snapshot.mode = "contest"
    if request.buyer_registry_version:
        from glassflow.modules.sales.service import registry
        buyers = registry(session, source.id, request.buyer_registry_version)
        session.add(ObjectRow(dataset_id=snapshot.id, kind="buyer_registry", id=buyers.id,
                               version=buyers.version, data=dict(buyers.data)))
    run_id = uid()
    inputs = {kind: [r.data for r in records(session, snapshot.id, kind)]
              for kind in ("materials", "stock", "orders", "applications", "questions", "dialogs", "kb")}
    manifest = {"run_id": run_id, "dataset_id": snapshot.id, "source_dataset_id": source.id,
        "source_hashes": snapshot.source_hashes, "input_hash": canonical_hash(snapshot.source_hashes),
        "schema_version": "0001_platform", "build": "0.1.0", "config_version": request.config_version,
        "python": platform.python_version(), "libraries": {name: importlib.metadata.version(name)
            for name in ("sqlalchemy", "pydantic", "scikit-learn", "scipy", "ortools")},
        "crm_policy": "reference-v1", "created_at": now(), "modules": request.modules,
        "solver": request.solver_config.model_dump(), "provider": request.ai_profile,
        "buyer_registry_version": request.buyer_registry_version, "files": {}, "validators": {},
        "official_accuracy": {"assistant": None, "crm": None, "quality": None},
        "validation_note": "Без evaluation KEY официальные закрытые баллы неизвестны"}
    row = ObjectRow(dataset_id=snapshot.id, kind="run", id=run_id, version=0, data=manifest)
    session.add(row)
    first_job = None
    for module in request.modules:
        if module == "cards":
            continue  # Dependency scheduled only after the final validated cutting result.
        job = enqueue(session, snapshot.id, module, {"dataset_id": snapshot.id, "run_id": run_id,
            "config_version": request.config_version, "solver_config": request.solver_config.model_dump(),
            "ai_profile": request.ai_profile, **inputs}, run_id)
        first_job = first_job or job
    if first_job is None:
        raise AppError(422, "CUTTING_REQUIRED", "Карточки требуют раскрой в том же прогоне.")
    session.flush()
    return job_dto(first_job).model_dump()


def find_run(session, run_id):
    row = session.scalar(select(ObjectRow).where(ObjectRow.kind == "run", ObjectRow.id == run_id))
    if row is None:
        raise AppError(404, "RUN_NOT_FOUND", "Прогон не найден.")
    return get_object(session, row.dataset_id, "run", run_id)


def run_view(session, run_id):
    row = find_run(session, run_id)
    jobs = session.scalars(select(JobRow).where(JobRow.run_id == run_id)).all()
    complete = {j.kind for j in jobs if j.state == "completed"}
    requested = set(row.data["modules"])
    waiting = any(j.state in {"queued", "running"} for j in jobs)
    status = "running" if waiting else "completed" if complete == requested else "partial" if complete else "blocked"
    return {"manifest": row.data, "status": status, "jobs": [job_dto(j).model_dump() for j in jobs],
            "missing_modules": sorted(requested - complete)}


def schedule_cards(factory):
    from glassflow.core.uow import write_transaction
    with write_transaction(factory) as session:
        for run in session.scalars(select(ObjectRow).where(ObjectRow.kind == "run")):
            if "cards" not in run.data["modules"]:
                continue
            jobs = list(session.scalars(select(JobRow).where(JobRow.run_id == run.id)))
            if any(j.kind == "cards" for j in jobs):
                continue
            cutting = next((j for j in jobs if j.kind == "cutting"), None)
            if cutting and cutting.state in {"queued", "running"}:
                continue
            if not cutting or cutting.state != "completed":
                card = enqueue(session, run.dataset_id, "cards", {}, run.id)
                card.state, card.stage, card.error_code = "failed", "dependency", "CUTTING_NOT_COMPLETED"
                card.stopped, card.finished_at = True, now()
            else:
                enqueue(session, run.dataset_id, "cards", {"dataset_id": run.dataset_id,
                    "run_id": run.id, "cutting_result": cutting.result,
                    "buyer_registry_version": run.data["buyer_registry_version"]}, run.id)
