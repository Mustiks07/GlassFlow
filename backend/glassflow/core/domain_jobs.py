"""Spawn-safe domain workers. Only pinned input bytes cross the process boundary."""

import asyncio
import json

from glassflow.contracts.cutting import CutPlan, SolveInput
from glassflow.modules.cutting.engine import CuttingEngine


def cutting_job(snapshot, context):
    data = SolveInput.model_validate(snapshot["cutting_snapshot"])
    baseline = (CutPlan.model_validate(snapshot["sale_baseline"]) if snapshot.get("sale_baseline") else
                CuttingEngine().solve(data, context))
    if not snapshot.get("sale_context"):
        return baseline.model_dump(mode="json")
    from glassflow.modules.cutting.sale_readiness import ensure_sale_readiness

    available = context.remaining_seconds() if hasattr(context, "remaining_seconds") else None
    requested_seconds = snapshot.get("sale_budget_seconds", 2.0)
    seconds = min(requested_seconds, max(.001, available - .1)) if available is not None else requested_seconds
    trusted = snapshot["sale_context"]
    outcome = ensure_sale_readiness(data, baseline, set(trusted["eligible_original_ids"]),
                                    trusted["registry_version"], budget_seconds=seconds, context=context)
    result = baseline.model_copy(deep=True)
    result.evidence["sale_readiness_bundle"] = json.dumps({"context": trusted, "outcome": outcome.model_dump(mode="json"),
                                               "connection_token": snapshot["connection_token"]}, ensure_ascii=False)
    return result.model_dump(mode="json")


def validate_cutting(snapshot, result):
    data = SolveInput.model_validate(snapshot["cutting_snapshot"])
    plan = CutPlan.model_validate(result)
    if not CuttingEngine().validate(data, plan).valid:
        return False
    if not snapshot.get("sale_context"):
        return True
    # Baseline solver incumbents precede bounded sale search. They remain valid
    # for the pinned geometric input; the final persistence hook requires the bundle.
    if "sale_readiness_bundle" not in plan.evidence:
        return True
    from glassflow.contracts.cutting import SaleReadiness

    bundle = json.loads(plan.evidence.get("sale_readiness_bundle", "{}"))
    if bundle.get("context") != snapshot["sale_context"] or bundle.get("connection_token") != snapshot["connection_token"]:
        return False
    outcome = SaleReadiness.model_validate(bundle["outcome"])
    baseline = plan.model_copy(deep=True)
    baseline.evidence.pop("sale_readiness_bundle", None)
    if outcome.baseline != baseline:
        return False
    return all(CuttingEngine().validate(data, candidate).valid for candidate in
               (outcome.alternative, outcome.tradeoff) if candidate is not None)


def store_cutting(session, dataset_id, result):
    from glassflow.modules.cutting.service import CuttingService

    plan = CutPlan.model_validate(result)
    service = CuttingService(session)
    encoded_bundle = plan.evidence.pop("sale_readiness_bundle", None)
    bundle = json.loads(encoded_bundle) if encoded_bundle else None
    if bundle is None:
        from sqlalchemy import select

        from glassflow.core.errors import AppError
        from glassflow.core.models import JobRow
        if any(j.input.get("sale_context") for j in session.scalars(select(JobRow).where(
                JobRow.dataset_id == dataset_id, JobRow.kind == "cutting", JobRow.state == "running"))):
            raise AppError(409, "SALE_CONTEXT_MISSING", "Итоговое задание должно содержать совместную проверку.")
    readiness = None
    stored = None
    if bundle:
        from sqlalchemy import select

        from glassflow.contracts.cutting import SaleReadiness
        from glassflow.core.errors import AppError
        from glassflow.core.models import JobRow
        from glassflow.core.snapshots import sale_readiness_snapshot

        # Recover the parent-owned input, never trust eligibility/fingerprints echoed by a child.
        candidates = [j for j in session.scalars(select(JobRow).where(JobRow.dataset_id == dataset_id,
            JobRow.kind == "cutting", JobRow.state == "running"))
            if j.input.get("connection_token") == bundle.get("connection_token")]
        if len(candidates) != 1:
            raise AppError(409, "SALE_CONTEXT_MISSING", "Не найдено исходное задание совместной проверки.")
        pinned = candidates[0].input
        data, current = sale_readiness_snapshot(session, dataset_id, pinned["sale_context"]["registry_version"],
            pinned["cutting_snapshot"]["config"], base_plan_id=pinned["sale_context"].get("base_plan_id"))
        if current != pinned["sale_context"] or bundle["context"] != pinned["sale_context"]:
            raise AppError(409, "SALE_CONTEXT_CHANGED", "Изменился склад или buyer evidence; исходный результат сохранен.")
        readiness = SaleReadiness.model_validate(bundle["outcome"])
        if readiness.baseline != plan or not CuttingEngine().validate(data, plan).valid:
            raise AppError(409, "SALE_BASELINE_INVALID", "Исходный план не прошел перепроверку.")
        existing = pinned.get("sale_baseline")
        stored = (service.get_plan(dataset_id, existing["plan_id"], existing["revision"]) if existing else
                  service.store_solver_plan(dataset_id, plan, base_plan_id=plan.parent_plan_id))
        eligible = set(current["eligible_original_ids"])
        used = {p.remnant_id for p in plan.placements}
        free = sorted(eligible - used)
        # Parent derives status and delta from actual layouts; metadata is diagnostic only.
        readiness.eligible_original_ids = sorted(eligible)
        readiness.baseline_free_eligible_ids = free
        readiness.registry_fingerprint = current["registry_fingerprint"]
        readiness.inventory_fingerprint = current["inventory_fingerprint"]
        readiness.input_fingerprint = current["input_fingerprint"]
        readiness.status = "ready_unchanged" if len(free) >= 5 else "evidence_shortage" if len(eligible) < 5 else "limited"
        if readiness.status in {"ready_unchanged", "evidence_shortage"}:
            if readiness.alternative or readiness.tradeoff:
                raise AppError(409, "SALE_SEARCH_UNNECESSARY", "Для текущих evidence пересчет не разрешен.")
            readiness.search_performed = False
        for name in ("alternative", "tradeoff"):
            candidate = getattr(readiness, name)
            if candidate is None:
                continue
            report = CuttingEngine().validate(data, candidate)
            candidate_free = sorted(eligible - {p.remnant_id for p in candidate.placements})
            if not report.valid or len(candidate_free) < 5:
                raise AppError(409, "SALE_CANDIDATE_INVALID", "Совместный вариант не прошел независимую проверку.")
            # Store revalidates geometry and recalculates metrics from canonical current parts.
            canonical = service.store_solver_plan(dataset_id, candidate)
            delta = canonical.metrics.covered_area_mm2 - stored.metrics.covered_area_mm2
            if (name == "alternative" and delta < 0) or (name == "tradeoff" and delta >= 0):
                raise AppError(409, "SALE_DELTA_INVALID", "Уступка площади не может быть незаметно принята.")
            setattr(readiness, name, canonical)
            readiness.delta_area_mm2 = delta
            readiness.candidate_free_eligible_ids = candidate_free
            if len(free) < 5 and len(eligible) >= 5:
                readiness.status = "ready_alternative" if name == "alternative" else "tradeoff_available"
    stored = stored or service.store_solver_plan(dataset_id, plan, base_plan_id=plan.parent_plan_id)
    baseline_ref = {"plan_id": stored.plan_id, "revision": stored.revision}
    if readiness:
        readiness.baseline = stored
        # Only a verified area-neutral/improving alternative is selected automatically.
        if readiness.status == "ready_alternative":
            stored = readiness.alternative
    exported = service.export(dataset_id, stored.plan_id, stored.revision)
    result.clear()
    result.update(stored.model_dump(mode="json"))
    result.update(plan_revision=stored.revision, validated=exported.validation.valid,
                  rows=[r.model_dump(mode="json") for r in exported.rows],
                  provenance={"plan_id": stored.plan_id, "revision": stored.revision,
                              "config": stored.config.model_dump(), "evidence": stored.evidence})
    if readiness:
        result.update(sale_readiness=readiness.model_dump(mode="json"), baseline_plan_ref=baseline_ref,
            selected_plan_ref={"plan_id": stored.plan_id, "revision": stored.revision},
            alternative_plan_ref=({"plan_id": readiness.alternative.plan_id, "revision": readiness.alternative.revision}
                                  if readiness.alternative else None),
            tradeoff_plan_ref=({"plan_id": readiness.tradeoff.plan_id, "revision": readiness.tradeoff.revision}
                               if readiness.tradeoff else None))


def engine_for(snapshot, context):
    import base64

    from glassflow.core.domain_runtime import runtime_for
    from glassflow.modules.intelligence.assistant.engine import AssistantEngine
    from glassflow.modules.intelligence.catalog.kb import parse_knowledge_base
    from glassflow.modules.intelligence.catalog.mapping import derive_all
    from glassflow.modules.intelligence.catalog.materials import parse_materials

    kb = parse_knowledge_base(base64.b64decode(snapshot["kb_bytes_b64"]) if snapshot.get("kb_bytes_b64")
                              else json.dumps(snapshot["kb"][0], ensure_ascii=False).encode("utf-8"))
    # Material mappings use the same canonical CSV parser as the HTTP service.
    import csv
    import io

    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(snapshot["materials"][0]))
    writer.writeheader()
    writer.writerows(snapshot["materials"])
    materials = parse_materials(base64.b64decode(snapshot["materials_bytes_b64"]) if snapshot.get("materials_bytes_b64")
                                else stream.getvalue().encode("utf-8"))
    runtime = runtime_for(snapshot.get("ai_settings", {}), context.private_config.get("api_key"))
    return AssistantEngine(kb, derive_all(kb, materials), dataset_id=snapshot["dataset_id"], runtime=runtime)


def assistant_job(snapshot, context):
    from glassflow.modules.intelligence.assistant.engine import cache_key
    from glassflow.modules.intelligence.assistant.local import TurnContext
    from glassflow.modules.platform.checkpoints import (
        payload_from_answer,
        row_fingerprint,
        validate_assistant_checkpoint,
    )

    engine = engine_for(snapshot, context)

    async def run():
        rows, paths = [], []
        reusable = {r["row_id"]: r for r in snapshot.get("accepted_rows", [])}
        proofs = {}
        for index, question in enumerate(snapshot["questions"]):
            context.progress("answering", index, len(snapshot["questions"]))
            row_id = question["id"]
            fingerprint = row_fingerprint(snapshot, row_id)
            previous = reusable.get(row_id)
            if previous and previous["fingerprint"] == fingerprint:
                payload = previous["payload"]
                rows.append({"id": row_id, **payload["row"]})
                paths.append({"id": row_id, **payload["provenance"], "source_path": payload["provenance"]["path"],
                              "path": "checkpoint_reuse", "resumed": True,
                              "source_job_id": previous.get("source_job_id")})
                continue
            models = engine.runtime.client.chain() if engine.runtime and engine.runtime.client else []
            semantic_key = cache_key(question["question"], engine.kb.version, models, {})
            available = context.remaining_seconds()
            if available is not None and engine.runtime and engine.runtime.client:
                for profile in (engine.runtime.profile, engine.runtime.client.profile):
                    profile.turn_deadline_s = max(.001, min(profile.turn_deadline_s, available))
                    profile.request_timeout_s = max(.001, min(profile.request_timeout_s, available))
            answer = await engine.turn(question["question"], TurnContext(), inventory_mode="none",
                                       allow_ai=snapshot.get("ai_profile") != "local_limited")
            payload = payload_from_answer(answer, proofs.get(semantic_key) if answer.cache_hit else None)
            payload["provenance"]["review_user_text"] = question["question"]
            if not validate_assistant_checkpoint(snapshot, row_id, fingerprint, payload):
                # Fail closed on incomplete/unreplayable model evidence. The model's output
                # is not promoted to a verified row merely because the child says so.
                local = engine.local.respond(question["question"], TurnContext(), inventory_mode="none")
                payload["row"]["answer"] = local.answer
                payload["tool_calls"] = []
                payload["inventory_used"] = False
                payload["provenance"].update(path="fallback", provider=None, model_id=None,
                    verifier_status="parent_policy_fallback", parent_verifier_rejected=True)
            if payload["tool_calls"]:
                proofs[semantic_key] = payload["tool_calls"]
            context.checkpoint(row_id, fingerprint, payload)
            rows.append({"id": row_id, **payload["row"]})
            paths.append({"id": row_id, **payload["provenance"], "resumed": False})
        return {"rows": rows, "provenance": {"kb_version": engine.local.kb.version, "answer_paths": paths}}

    return asyncio.run(run())


from glassflow.modules.platform.checkpoints import validate_assistant_checkpoint  # noqa: E402

assistant_job.checkpoint_validator = validate_assistant_checkpoint
assistant_job.requires_complete_checkpoints = True


def store_assistant(session, dataset_id, result):
    from glassflow.modules.intelligence.reviews import record_accepted_batch_reviews
    record_accepted_batch_reviews(session, dataset_id, result)


def quality_job(snapshot, context):
    from glassflow.modules.intelligence.quality.dialogs import check_dialog

    engine = engine_for(snapshot, context)
    verdicts = []
    for index, dialog in enumerate(snapshot["dialogs"]):
        context.progress("checking", index, len(snapshot["dialogs"]))
        verdicts.append(check_dialog(engine.local.kb, dialog["id"], dialog["client"], dialog["manager"]))
    return {"rows": [{"id": v.id, "verdict": v.verdict, "correct": v.correct} for v in verdicts],
            "provenance": {"kb_version": engine.local.kb.version, "verdicts": [v.model_dump(mode="json") for v in verdicts]}}


def cards_job(snapshot, context):
    # DB-dependent matching runs in the coordinator's short result transaction.
    context.progress("matching", 0, 5)
    return snapshot


def store_cards(session, dataset_id, result):
    from glassflow.contracts.crm import CardsRequest
    from glassflow.core.composition import domain_services
    from glassflow.modules.sales.service import generate_cards

    plan = result["cutting_result"]
    cards = generate_cards(session, CardsRequest(dataset_id=dataset_id, plan_id=plan["plan_id"],
        plan_revision=plan["plan_revision"], buyer_registry_version=result["buyer_registry_version"]),
        domain_services(), "run-cards")
    result.update(plan_id=plan["plan_id"], plan_revision=plan["plan_revision"],
                  card_ids=[c["card_id"] for c in cards["cards"]], provenance={"matching_policy": "evidence-v1"})
