"""N02 accepted-row identity and independent parent-side verifier replay."""

from functools import lru_cache

from glassflow.core.resources import build_info
from glassflow.core.uow import canonical_hash

POLICY_VERSION = "parent-assistant-row-v1"


@lru_cache(maxsize=1)
def verifier_identity():
    from glassflow.modules.intelligence.assistant.prompts import PROMPT_VERSION
    from glassflow.modules.intelligence.assistant.tools import TOOLS
    return {"policy": POLICY_VERSION, "prompt": PROMPT_VERSION,
            "tools_schema": canonical_hash({k: t.parameters for k, t in TOOLS.items()}),
            "runtime_source_digest": build_info()["source_digest"]}


def row_fingerprint(snapshot, row_id):
    question = next((q for q in snapshot.get("questions", []) if q["id"] == row_id), None)
    if question is None:
        return None
    settings = {k: v for k, v in snapshot.get("ai_settings", {}).items()
                if k not in {"api_key", "secret_present"}}
    return canonical_hash({"dataset_id": snapshot["dataset_id"], "question": question,
        "exact_input_hashes": snapshot.get("input_source_hashes", {}),
        "kb": snapshot.get("kb_bytes_b64", snapshot.get("kb")),
        "materials": snapshot.get("materials_bytes_b64", snapshot.get("materials")),
        "profile": snapshot.get("ai_profile"), "model_config": settings,
        "inventory_context": "none", "verifier": verifier_identity()})


def payload_from_answer(answer, proof=None):
    calls = proof or ([{"name": e.name, "arguments": e.arguments} for e in answer.llm.executions if e.status == "ok"]
                      if answer.llm and answer.answer_path == "llm_tools" else [])
    return {"row": {"answer": answer.answer}, "tool_calls": calls,
            "inventory_used": bool(answer.tool_context and answer.tool_context.remnant_checked),
            "provenance": {"path": answer.answer_path, "provider": answer.provider, "model_id": answer.model_id,
                "verifier_status": answer.verifier_status, "cache_hit": answer.cache_hit,
                "llm_status": answer.llm.status if answer.llm else None,
                "llm_model_id": answer.llm.model_id if answer.llm else None,
                "provider_error_kind": answer.llm.error.kind if answer.llm and answer.llm.error else None,
                "provider_error_status": answer.llm.error.status if answer.llm and answer.llm.error else None}}


def validate_assistant_checkpoint(snapshot, row_id, fingerprint, payload):
    """No serialized arbitrary FactSet is trusted; prices/rules are recreated from pinned KB."""
    from glassflow.core.domain_jobs import engine_for
    from glassflow.modules.intelligence.assistant.local import TurnContext
    from glassflow.modules.intelligence.assistant.tools import ToolContext, execute_tool
    from glassflow.modules.intelligence.assistant.verifier import verify_answer

    if fingerprint != row_fingerprint(snapshot, row_id) or payload.get("inventory_used") is not False:
        return False
    if set(payload) != {"row", "tool_calls", "inventory_used", "provenance"}:
        return False
    if set(payload["row"]) != {"answer"} or not isinstance(payload["row"]["answer"], str):
        return False
    if set(payload["provenance"]) - {"path", "provider", "model_id", "verifier_status", "cache_hit",
            "llm_status", "llm_model_id", "parent_verifier_rejected", "provider_error_kind", "provider_error_status"}:
        return False
    question = next(q for q in snapshot["questions"] if q["id"] == row_id)
    validation_context = type("ValidationContext", (), {"private_config": {}})()
    engine = engine_for(snapshot, validation_context)
    path = payload["provenance"].get("path")
    if path in {"deterministic", "fallback"}:
        canonical = engine.local.respond(question["question"], TurnContext(), inventory_mode="none")
        return payload["row"]["answer"] == canonical.answer
    if path != "llm_tools" or payload["provenance"].get("verifier_status") != "supported":
        return False
    calls = payload["tool_calls"]
    if not isinstance(calls, list) or len(calls) > 36:
        return False
    allowed = ["search_catalog", "get_product", "get_rules", "calculate_quote", "resolve_material",
               "recommend_accessories", "verify_answer", "submit_answer"]
    ctx = ToolContext(engine.local.kb, engine.mappings, snapshot["dataset_id"], user_text=question["question"])
    for call in calls:
        if not isinstance(call, dict) or set(call) != {"name", "arguments"} or call["name"] not in allowed:
            return False
        result = execute_tool(ctx, call["name"], call["arguments"], allowed)
        if result.status != "ok":
            return False
    if ctx.remnant_checked or any(f.source_ref.startswith("inventory:") for f in ctx.facts.facts):
        return False
    return verify_answer(payload["row"]["answer"], ctx.facts, question["question"]).status == "supported"


def checkpoint_record(row_id, fingerprint, payload):
    return {"row_id": row_id, "fingerprint": fingerprint, "payload": payload,
            "payload_hash": canonical_hash(payload)}
