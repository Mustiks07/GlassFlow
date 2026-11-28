"""Spawn-safe domain workers. Only pinned input bytes cross the process boundary."""

import asyncio
import json

from glassflow.contracts.cutting import CutPlan, SolveInput
from glassflow.modules.cutting.engine import CuttingEngine


def cutting_job(snapshot, context):
    return CuttingEngine().solve(SolveInput.model_validate(snapshot["cutting_snapshot"]), context).model_dump(mode="json")


def validate_cutting(snapshot, result):
    return CuttingEngine().validate(SolveInput.model_validate(snapshot["cutting_snapshot"]), CutPlan.model_validate(result)).valid


def store_cutting(session, dataset_id, result):
    from glassflow.modules.cutting.service import CuttingService

    plan = CutPlan.model_validate(result)
    service = CuttingService(session)
    stored = service.store_solver_plan(dataset_id, plan, base_plan_id=plan.parent_plan_id)
    exported = service.export(dataset_id, stored.plan_id, stored.revision)
    result.clear()
    result.update(stored.model_dump(mode="json"))
    result.update(plan_revision=stored.revision, validated=exported.validation.valid,
                  rows=[r.model_dump(mode="json") for r in exported.rows],
                  provenance={"plan_id": stored.plan_id, "revision": stored.revision,
                              "config": stored.config.model_dump(), "evidence": stored.evidence})


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
    from glassflow.modules.intelligence.assistant.local import TurnContext

    engine = engine_for(snapshot, context)

    async def run():
        rows, paths = [], []
        for index, question in enumerate(snapshot["questions"]):
            context.progress("answering", index, len(snapshot["questions"]))
            answer = await engine.turn(question["question"], TurnContext(), inventory_mode="none",
                                       allow_ai=snapshot.get("ai_profile") != "local_limited")
            rows.append({"id": question["id"], "answer": answer.answer})
            paths.append({"id": question["id"], "path": answer.answer_path, "provider": answer.provider,
                          "model_id": answer.model_id, "verifier_status": answer.verifier_status})
        return {"rows": rows, "provenance": {"kb_version": engine.local.kb.version, "answer_paths": paths}}

    return asyncio.run(run())


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
