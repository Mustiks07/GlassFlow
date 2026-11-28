import importlib.metadata
import os
import platform

from sqlalchemy import select

from glassflow.core.db import SCHEMA_HEAD
from glassflow.core.errors import AppError
from glassflow.core.jobs import enqueue, job_dto
from glassflow.core.models import JobRow, ObjectRow, now, uid
from glassflow.core.resources import build_info
from glassflow.core.uow import canonical_hash, get_object
from glassflow.modules.crm.service import rank_rows
from glassflow.modules.platform.budgets import bound_solver, budget_view, create_budget, remaining
from glassflow.modules.platform.imports import dataset, records, working_copy

MODULE_FILES = {
    "cutting": "solution.csv",
    "assistant": "answers.csv",
    "crm": "picks.csv",
    "quality": "verdicts.csv",
    "cards": "sale_cards.csv",
}


def crm_job(snapshot, context):
    result = rank_rows(snapshot["applications"])
    context.progress("ranked", 25, 25)
    return {
        "rows": [{"app_id": r.app_id} for r in result.rows],
        "policy": result.policy_version,
        "observed_precision": result.observed_precision,
        "provenance": {
            "policy_version": result.policy_version,
            "feature_version": "crm-v1",
            "model_hash": None,
        },
    }


def create_run(session, request, services, correlation):
    from glassflow.modules.platform.system import get_settings

    settings = get_settings(session, {})
    if request.ai_profile != "local_limited" and request.ai_profile != settings.profile:
        raise AppError(409, "AI_PROFILE_MISMATCH", "Сначала выберите нужный AI-профиль в настройках.")
    if request.solver_config.workers > max(1, (os.cpu_count() or 1) - 1):
        raise AppError(422, "CPU_BUDGET_EXCEEDED", "Число потоков превышает CPU-1.")
    if request.solver_config.time_limit_seconds > 3600:
        raise AppError(422, "TIME_BUDGET_EXCEEDED", "Бюджет одного задания ограничен часом.")
    source = dataset(session, request.dataset_id)
    import hashlib

    from glassflow.core.resources import resource_root

    references = {"materials": "1_ostatki/materials.csv", "kb": "2_assistant_crm/ksm_knowledge_base.json"}
    for kind, relative in references.items():
        path = resource_root() / "inputs/PACK_for_teams" / relative
        if (
            not path.is_file()
            or source.source_hashes.get(kind) != hashlib.sha256(path.read_bytes()).hexdigest()
        ):
            raise AppError(
                409,
                "CONTEST_REFERENCE_MISMATCH",
                "Конкурсный прогон использует исходные materials и KB организаторов.",
            )
    if source.mode == "workspace":
        raise AppError(409, "IMMUTABLE_SOURCE_REQUIRED", "Выберите исходный снимок для конкурсного прогона.")
    if not request.modules or len(set(request.modules)) != len(request.modules):
        raise AppError(422, "INVALID_MODULES", "Выберите неповторяющиеся модули.")
    if request.total_budget_seconds is not None and set(request.modules) == set(MODULE_FILES) and not request.buyer_registry_version:
        raise AppError(409, "BUYER_REGISTRY_REQUIRED", "Полный бюджетный комплект требует закрепленного реестра покупателей.")
    copy = working_copy(session, source.id, f"Прогон: {source.name}", services, correlation, mode="contest")
    snapshot = dataset(session, copy["dataset_id"])
    if request.buyer_registry_version:
        from glassflow.modules.sales.service import registry

        buyers = registry(session, source.id, request.buyer_registry_version)
        session.add(
            ObjectRow(
                dataset_id=snapshot.id,
                kind="buyer_registry",
                id=buyers.id,
                version=buyers.version,
                data=dict(buyers.data),
            )
        )
    run_id = uid()
    inputs = {
        kind: [r.data for r in records(session, snapshot.id, kind)]
        for kind in ("materials", "stock", "orders", "applications", "questions", "dialogs", "kb")
    }
    manifest = {
        "run_id": run_id,
        "dataset_id": snapshot.id,
        "source_dataset_id": source.id,
        "source_hashes": snapshot.source_hashes,
        "input_hash": canonical_hash(snapshot.source_hashes),
        "schema_version": SCHEMA_HEAD,
        "build": "0.1.0",
        "build_info": build_info(),
        "config_version": request.config_version,
        "python": platform.python_version(),
        "libraries": {
            name: importlib.metadata.version(name)
            for name in ("sqlalchemy", "pydantic", "scikit-learn", "scipy", "ortools")
        },
        "crm_policy": "reference-v1",
        "created_at": now(),
        "modules": request.modules,
        "solver": request.solver_config.model_dump(),
        "provider": request.ai_profile,
        "ai_settings": settings.model_dump(exclude={"secret_present"}),
        "buyer_registry_version": request.buyer_registry_version,
        "files": {},
        "validators": {},
        "official_accuracy": {"assistant": None, "crm": None, "quality": None},
        "validation_note": "Без evaluation KEY официальные закрытые баллы неизвестны",
    }
    budget = (create_budget(request.total_budget_seconds, request.export_reserve_seconds,
                            request.solver_config.model_dump()) if request.total_budget_seconds is not None else None)
    if budget:
        manifest["budget"] = budget
    sale_context = None
    from glassflow.core.domain_jobs import cutting_job
    # Explicit Services with no domain handler remain dependency-isolation seams;
    # they cannot claim a production sale-readiness result. Real composition always registers this handler.
    connected_cutting = getattr(services.job_handlers.get("cutting"), "function", None) is cutting_job
    manifest["sale_readiness_enabled"] = bool(connected_cutting and request.buyer_registry_version)
    if "cutting" in request.modules and request.buyer_registry_version and connected_cutting:
        from glassflow.core.snapshots import sale_readiness_snapshot
        live_cutting, sale_context = sale_readiness_snapshot(session, snapshot.id, request.buyer_registry_version,
            bound_solver(request.solver_config.model_dump(), budget, baseline=True))
    row = ObjectRow(dataset_id=snapshot.id, kind="run", id=run_id, version=0, data=manifest)
    session.add(row)
    first_job = None
    ordered_modules = (sorted(request.modules, key=lambda m: {"quality": 0, "crm": 1, "cutting": 2,
        "assistant": 3, "cards": 4}[m]) if budget else request.modules)
    for module in ordered_modules:
        if module == "cards":
            continue  # Dependency scheduled only after the final validated cutting result.
        from glassflow.core.snapshots import cutting_snapshot

        solver = bound_solver(request.solver_config.model_dump(), budget, baseline=True)
        typed_cutting = (
            (live_cutting if sale_context else cutting_snapshot(snapshot.id, inputs, solver)).model_dump(mode="json")
            if module == "cutting"
            else None
        )
        allowed_inputs = {"cutting": ("materials", "stock", "orders"), "assistant": ("kb", "questions", "materials"),
                          "crm": ("applications",), "quality": ("kb", "dialogs", "materials")}[module]
        import base64

        from glassflow.core.models import SourceRow
        source_bytes = {r.kind: r.content for r in session.scalars(select(SourceRow).where(SourceRow.dataset_id == snapshot.id))}
        job = enqueue(
            session,
            snapshot.id,
            module,
            {
                "dataset_id": snapshot.id,
                "run_id": run_id,
                "config_version": request.config_version,
                "solver_config": solver,
                **({"sale_context": sale_context, "connection_token": uid()}
                   if module == "cutting" and sale_context else {}),
                **({"run_budget": budget, "phase": "baseline"} if budget else {}),
                "ai_profile": request.ai_profile,
                "ai_settings": settings.model_dump(exclude={"secret_present"}),
                "input_source_hashes": {kind: snapshot.source_hashes[kind] for kind in allowed_inputs},
                **{f"{kind}_bytes_b64": base64.b64encode(source_bytes[kind]).decode("ascii")
                   for kind in ("kb", "materials") if kind in allowed_inputs},
                "cutting_snapshot": typed_cutting,
                **{kind: inputs[kind] for kind in allowed_inputs},
            },
            run_id,
        )
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


def enqueue_sale_readiness(session, dataset_id, baseline_plan_id, baseline_revision, registry_version,
                           *, budget_seconds=2):
    """Standalone server seam. Route owns authorization, idempotency and transaction."""
    from glassflow.core.errors import AppError
    from glassflow.core.snapshots import sale_readiness_snapshot
    from glassflow.modules.cutting.service import CuttingService
    if not 0 < budget_seconds <= 30:
        raise AppError(422, "SALE_BUDGET_INVALID", "Бюджет совместной проверки должен быть от0 до30 секунд.")
    service = CuttingService(session)
    baseline = service.get_plan(dataset_id, baseline_plan_id, baseline_revision)
    data, facts = sale_readiness_snapshot(session, dataset_id, registry_version,
                                         baseline.config or {}, base_plan_id=baseline_plan_id)
    if not service.validate(dataset_id, baseline_plan_id, baseline_revision).valid:
        raise AppError(409, "STALE_PLAN", "Исходный план не соответствует текущему складу.")
    return job_dto(enqueue(session, dataset_id, "cutting", {"dataset_id": dataset_id,
        "cutting_snapshot": data.model_dump(mode="json"), "solver_config": data.config.model_dump(),
        "sale_baseline": baseline.model_dump(mode="json"), "sale_context": facts, "connection_token": uid(),
        "sale_budget_seconds": budget_seconds})).model_dump()


def latest_jobs(session, run_id):
    result = {}
    for j in session.scalars(
            select(JobRow).where(JobRow.run_id == run_id).order_by(JobRow.created_at, JobRow.id)
        ):
        if j.kind == "cutting" and j.input.get("phase") == "improvement":
            if j.state != "completed" or not (j.result or {}).get("promotion", {}).get("promoted"):
                continue
            current = result.get("cutting")
            metrics, before = (j.result or {}).get("metrics", {}), (current.result or {}).get("metrics", {}) if current else {}
            if (metrics.get("covered_area_mm2", -1), metrics.get("fully_covered_orders", 0)) <= (
                    before.get("covered_area_mm2", -1), before.get("fully_covered_orders", 0)):
                continue
        result[j.kind] = j
    return result


def cards_dispatch_due(data, cutting, previous):
    """Whether the next coordinator tick will create this dependency outcome."""
    if "cards" not in data["modules"]:
        return False
    if previous and (not data.get("budget") or not cutting or previous.input.get("cutting_job_id") == cutting.id):
        return False
    return not cutting or cutting.state not in {"queued", "running"}


def improvement_dispatch_due(data, selected):
    budget = data.get("budget")
    if (not budget or not data.get("accepted_export_id") or budget.get("improvement_job_id")
            or "cutting" not in data["modules"] or remaining(budget, work=True) <= 7):
        return False
    requested = budget["requested_solver"]
    return (requested.get("profile") != "quick" and requested.get("time_limit_seconds", 5) > 5
            and selected is not None and selected.state == "completed")


def run_view(session, run_id):
    row = find_run(session, run_id)
    latest = latest_jobs(session, run_id)
    jobs = list(latest.values())
    complete = {j.kind for j in jobs if j.state == "completed"}
    requested = set(row.data["modules"])
    waiting = any(j.state in {"queued", "running"} for j in session.scalars(select(JobRow).where(JobRow.run_id == run_id)))
    budget = row.data.get("budget")
    cutting = latest.get("cutting")
    if (cutting and cutting.state == "completed" and cards_dispatch_due(row.data, cutting, latest.get("cards"))
            and (not budget or remaining(budget, work=True) > 0)):
        waiting = True
    waiting = waiting or improvement_dispatch_due(row.data, cutting)
    if budget and set(row.data["modules"]) == set(MODULE_FILES) and remaining(budget) > 0:
        refs = {j.kind: {"job_id": j.id, "state": j.state} for j in jobs}
        if complete == requested and row.data.get("accepted_result_refs") != refs:
            waiting = waiting or budget.get("export_status") not in {"partial", "failed"}
    status = (
        "running"
        if waiting
        else "completed"
        if complete == requested
        else "partial"
        if complete
        else "blocked"
    )
    return {
        "manifest": row.data,
        "status": status,
        "jobs": [job_dto(j).model_dump() for j in jobs],
        "missing_modules": sorted(requested - complete),
        "version": row.version,
        "budget": budget_view(budget),
    }


def schedule_cards(factory):
    from glassflow.core.uow import write_transaction

    with write_transaction(factory) as session:
        for run in session.scalars(select(ObjectRow).where(ObjectRow.kind == "run")):
            schedule_improvement(session, run)
            if "cards" not in run.data["modules"]:
                continue
            jobs = list(latest_jobs(session, run.id).values())
            cutting = next((j for j in jobs if j.kind == "cutting"), None)
            previous = next((j for j in jobs if j.kind == "cards"), None)
            if not cards_dispatch_due(run.data, cutting, previous):
                continue
            if not cutting or cutting.state != "completed":
                card = enqueue(session, run.dataset_id, "cards",
                               {"cutting_job_id": cutting.id} if cutting else {}, run.id)
                card.state, card.stage, card.error_code = "failed", "dependency", "CUTTING_NOT_COMPLETED"
                card.stopped, card.finished_at = True, now()
            else:
                enqueue(
                    session,
                    run.dataset_id,
                    "cards",
                    {
                        "dataset_id": run.dataset_id,
                        "run_id": run.id,
                        "cutting_result": cutting.result,
                        "buyer_registry_version": run.data["buyer_registry_version"],
                        "cutting_job_id": cutting.id,
                        **({"run_budget": run.data["budget"]} if run.data.get("budget") else {}),
                    },
                    run.id,
                )


def schedule_improvement(session, run):
    from copy import deepcopy

    from glassflow.core.uow import audit

    budget = run.data.get("budget")
    if not budget or not run.data.get("accepted_export_id"):
        return
    selected = latest_jobs(session, run.id).get("cutting")
    if not improvement_dispatch_due(run.data, selected):
        return
    requested = budget["requested_solver"]
    snapshot = deepcopy(selected.input)
    solver = bound_solver(requested, budget)
    snapshot.update(phase="improvement", run_budget=deepcopy(budget), solver_config=solver,
                    baseline_metrics=deepcopy(selected.result.get("metrics", {})))
    snapshot["cutting_snapshot"]["config"] = solver
    if snapshot.get("sale_context"):
        from glassflow.core.snapshots import sale_readiness_snapshot
        current, facts = sale_readiness_snapshot(session, run.dataset_id, run.data["buyer_registry_version"], solver)
        snapshot.update(cutting_snapshot=current.model_dump(mode="json"), sale_context=facts, connection_token=uid())
    snapshot.pop("checkpoint_lineage", None)
    job = enqueue(session, run.dataset_id, "cutting", snapshot, run.id)
    budget = {**budget, "phase": "improving", "improvement_job_id": job.id,
              "baseline_cutting_job_id": selected.id}
    run.data = {**run.data, "budget": budget}
    audit(session, run.dataset_id, "run.improvement_scheduled", run.id, "coordinator",
          baseline_job_id=selected.id, improvement_job_id=job.id, budget_version=budget["version"])


def renew_budget(session, run_id, body, correlation):
    from glassflow.core.uow import audit
    run = get_object(session, body.dataset_id, "run", run_id, body.expected_version)
    if session.scalar(select(JobRow).where(JobRow.run_id == run_id, JobRow.state.in_(["queued", "running"]))):
        raise AppError(409, "RUN_ACTIVE", "Сначала остановите текущие задания; бюджет не продлевается скрыто.")
    previous = run.data.get("budget") or {}
    budget = create_budget(body.total_budget_seconds, body.export_reserve_seconds, run.data["solver"],
                           version=previous.get("version", -1) + 1)
    run.data = {**run.data, "budget": budget}
    run.version += 1
    audit(session, run.dataset_id, "run.budget_renewed", run.id, correlation,
          budget_version=budget["version"], deadline_utc=budget["deadline_utc"], previous_budget=previous,
          renewed_budget=budget)
    return run_view(session, run_id)


def auto_export_candidates(factory):
    """Claim one small export task; the actual filesystem/validator work runs elsewhere."""
    from glassflow.core.uow import write_transaction
    with write_transaction(factory) as session:
        for run in session.scalars(select(ObjectRow).where(ObjectRow.kind == "run").order_by(ObjectRow.id)):
            budget = run.data.get("budget")
            if not budget or set(run.data["modules"]) != set(MODULE_FILES) or remaining(budget) <= 0:
                continue
            jobs = latest_jobs(session, run.id)
            if set(jobs) != set(MODULE_FILES) or any(j.state != "completed" for j in jobs.values()):
                continue
            refs = {k: {"job_id": j.id, "state": j.state} for k, j in jobs.items()}
            if run.data.get("accepted_result_refs") == refs:
                continue
            key = canonical_hash({"refs": refs, "budget_version": budget["version"]})
            if budget.get("export_candidate_key") == key and budget.get("export_status") != "interrupted":
                continue
            attempt = uid()
            run.data = {**run.data, "budget": {**budget, "export_candidate_key": key,
                        "export_attempt_id": attempt, "export_status": "running"}}
            return run.id, budget["version"], attempt
    return None
