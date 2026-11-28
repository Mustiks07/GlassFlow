"""Canonical selection of comparable cutting results and human-attested labor."""

from sqlalchemy import select

from glassflow.contracts.economics import EconomicInputs, EconomicsCreate, EconomicSource
from glassflow.core.errors import AppError
from glassflow.core.models import ObjectRow
from glassflow.core.uow import canonical_hash, get_object
from glassflow.modules.insights.passports import passport
from glassflow.modules.platform import economics_service, labor
from glassflow.modules.platform.imports import dataset


def sources(session, dataset_id, services, data_dir, warnings=None):
    owner = dataset(session, dataset_id)
    scope = {owner.id, owner.parent_id}
    if not services.readiness.get("cutting"):
        raise AppError(503, "CUTTING_UNAVAILABLE", "Для выбора результатов нужен модуль раскроя.")
    from glassflow.modules.cutting.service import CuttingService
    cutting = CuttingService(session)
    rows = []

    def add(d, plan, run_id=None):
        if plan.status not in {"validated", "committed", "superseded"} or plan.metrics.invalid or plan.metrics.missing:
            return
        provenance = dataset(session, d).source_hashes
        key = canonical_hash({"sources": {k: provenance[k] for k in ("stock", "orders", "materials")},
                              "inventory": plan.inventory_version,
                              "locks": [p.model_dump(mode="json") for p in plan.requested_locks],
                              "minimum_free": plan.config.minimum_free_remnants if plan.config else None})
        reference = f"plan:{d}:{plan.plan_id}:{plan.revision}"
        profile = plan.config.profile if plan.config else "import"
        name = {"quick": "Быстрый", "standard": "Обычный", "extended": "Расширенный", "import": "Импортированный"}.get(profile, "Проверенный")
        rows.append(EconomicSource(reference=reference, label=f"{name} · ревизия {plan.revision}", created_at=plan.created_at,
            comparison_key=key, material_value_tg=str(plan.metrics.replacement_value_tg), plan_id=plan.plan_id,
            revision=plan.revision, dataset_id=d, run_id=run_id))

    for summary in cutting.list_plans(dataset_id):
        add(dataset_id, cutting.get_plan(dataset_id, summary.plan_id, summary.revision))
    runs = session.scalars(select(ObjectRow).where(ObjectRow.kind == "run")).all()
    for run in runs:
        if run.data.get("source_dataset_id") not in scope or not run.data.get("accepted_export_id"):
            continue
        # Read the immutable accepted manifest and verify its real CSV bytes.
        try:
            p = passport(session, data_dir, run.id, run.data["source_dataset_id"], "accepted")
        except AppError:
            if warnings is not None:
                warnings.append("Один из прежних принятых комплектов не прошёл проверку файлов и исключён из выбора. Проверьте его паспорт.")
            continue
        ref = p.manifest.get("result_refs", {}).get("cutting")
        # Canonical result references are stored with the run's accepted snapshot.
        ref = ref or run.data.get("accepted_result_refs", {}).get("cutting")
        if not ref:
            continue
        from glassflow.core.models import JobRow
        job = session.get(JobRow, ref["job_id"])
        result = job.result or job.last_valid_result or {}
        if result.get("plan_id"):
            add(run.dataset_id, cutting.get_plan(run.dataset_id, result["plan_id"], result.get("revision")), run.id)
    return rows


def create(session, body, services, data_dir, correlation):
    choices = {r.reference: r for r in sources(session, body.dataset_id, services, data_dir)}
    first, final = choices.get(body.baseline_ref), choices.get(body.final_ref)
    if not first or not final:
        raise AppError(409, "ECONOMIC_SOURCE_STALE", "Результат изменился или больше не проходит проверку. Обновите список.")
    if first.reference == final.reference or first.comparison_key != final.comparison_key:
        raise AppError(409, "ECONOMIC_INPUTS_NOT_COMPARABLE", "Нужны два разных результата на одинаковых входах, закреплениях и состоянии склада.")
    get_object(session, body.dataset_id, "labor_study", body.study_id, body.study_version)
    measured = labor.export(session, body.dataset_id, body.study_id)
    inputs = EconomicInputs(**body.assumptions.model_dump(), measurement_status="supplied_measurements",
        labor_studies=measured["labor_studies"], final_material_value_tg=final.material_value_tg,
        baseline_material_value_tg=first.material_value_tg, baseline_description=first.label,
        baseline_validation_ref=f"{first.reference}#comparison={first.comparison_key}",
        final_validation_ref=f"{final.reference}#comparison={final.comparison_key}")
    return economics_service.calculate(session, EconomicsCreate(dataset_id=body.dataset_id, name=body.name, inputs=inputs), correlation)
