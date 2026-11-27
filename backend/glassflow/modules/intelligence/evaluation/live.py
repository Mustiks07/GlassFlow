"""Live evaluation of the ONLINE path (real provider, real network, real quota).

Runs cases with ``strategy="ai_first"`` so the model answers every turn through the local
tools; deterministic fallback still protects the shown text. Records the actual model,
latency, attempts, tokens, tool errors, verifier rejections and expectation results.
Never stores keys or prompt text.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ..assistant.local import TurnContext
from ..assistant.prompts import PROMPT_VERSION
from ..assistant.verifier import verify_answer
from ..providers.policy import AIProfile, MemoryLedger, ModelRef, validate_profile
from ..providers.settings import AIRuntime, EnvSecrets, build_runtime
from .runner import CASES_PATH, DATASET, _p95, build_environment, has_price_claim, numbers

CRITICAL = ["E026", "E027", "E028", "E031", "E038", "E053", "E054", "E065", "E069", "E072", "E079", "E080"]
BROAD = CRITICAL + ["E015", "E020", "E041", "E047", "E061", "E074", "E084", "H004", "H005", "H016", "H026", "H030"]


def _ref(label: str) -> ModelRef:
    provider, _, model = label.partition(":")
    return ModelRef(provider=provider, model_id=model)  # type: ignore[arg-type]


def _cases(ids: list[str]) -> list[dict]:
    pool = {}
    for path in (CASES_PATH, CASES_PATH.with_name("cases_holdout.json")):
        for case in json.loads(path.read_text(encoding="utf-8"))["cases"]:
            pool[case["id"]] = case
    return [pool[i] for i in ids if i in pool]


def _check(case: dict, answer: str, status: str, facts, user_text: str) -> tuple[bool, list[str], list[str]]:
    expect = case["expect"]
    got = numbers(answer)
    reasons = []
    for value in expect.get("numbers", []):
        if not any(abs(g - value) <= 0.5 for g in got):
            reasons.append(f"missing_number:{value}")
    for value in expect.get("absent_numbers", []):
        if any(abs(g - value) <= 0.005 for g in got):
            reasons.append(f"forbidden_number:{value}")
    low = answer.lower()
    if expect.get("contains_any") and not any(w.lower() in low for w in expect["contains_any"]):
        reasons.append("missing_any")
    for word in expect.get("not_contains", []):
        if word.lower() in low:
            reasons.append(f"forbidden_text:{word}")
    if expect.get("status") and status not in expect["status"]:
        reasons.append(f"status:{status}")
    if expect.get("no_price_claim") and has_price_claim(answer):
        reasons.append("price_like_claim_in_unknown_answer")
    claims = verify_answer(answer, facts, user_text).unsupported
    return not reasons and not claims, reasons, claims


def evaluate_live(
    pack: Path,
    out: Path,
    *,
    model: str,
    fallbacks: list[str] | None = None,
    case_ids: list[str] | None = None,
    repeats: int = 1,
    rpm: int = 12,
    name: str | None = None,
) -> dict[str, object]:
    out.mkdir(parents=True, exist_ok=True)
    env = build_environment(pack, allow_ai=False)
    profile = AIProfile(
        name="live-eval",
        primary=_ref(model),
        fallbacks=[_ref(f) for f in (fallbacks or [])],
        rpm=rpm,
        rpd=1000,
        turn_deadline_s=90,
        request_timeout_s=45,
    )
    errors = validate_profile(profile)
    if errors:
        raise SystemExit(f"profile rejected before any network call: {errors}")
    ledger = MemoryLedger()
    runtime: AIRuntime = build_runtime(profile, EnvSecrets(), prompt_version=PROMPT_VERSION, ledger=ledger)
    if not runtime.available:
        raise SystemExit(f"AI runtime unavailable: {runtime.status} {runtime.reason_ru}")
    catalog = env.service.catalog_for(DATASET)
    engine = env.service._engine(catalog)
    engine.runtime = runtime
    engine.cache = type(engine.cache)(capacity=0)  # no answer cache in measurements
    runs = []
    turn_latencies = []
    for case in _cases(case_ids or CRITICAL):
        for repeat in range(repeats):
            context = TurnContext()
            first_entry = len(ledger.entries)
            result = None
            started = time.monotonic()
            for text in case["turns"]:
                turn_started = time.monotonic()
                result = asyncio.run(engine.turn(text, context, strategy="ai_first"))
                turn_latencies.append((time.monotonic() - turn_started) * 1000)
                context = result.local.context
            assert result is not None
            facts = result.tool_context.facts if result.tool_context is not None else result.local.facts
            ok, reasons, claims = _check(case, result.answer, result.status, facts, " ".join(case["turns"]))
            entries = ledger.entries[first_entry:]
            llm = result.llm
            runs.append({
                "id": case["id"], "group": case["group"], "repeat": repeat, "ok": ok, "reasons": reasons,
                "unsupported_shown_claims": claims, "answer": result.answer, "answer_path": result.answer_path,
                "verifier_status": result.verifier_status, "mode": result.mode, "model_id": result.model_id,
                "seconds": round(time.monotonic() - started, 2),
                "model_attempts": len(entries), "provider_errors": [e.error_kind for e in entries if e.status != "ok"],
                "provider_error_messages": [e.error_message for e in entries if e.status != "ok"],
                "input_tokens": sum(e.input_tokens or 0 for e in entries), "output_tokens": sum(e.output_tokens or 0 for e in entries),
                "thought_tokens": sum(e.thought_tokens or 0 for e in entries),
                "tools": [(x.name, x.status) for x in (llm.executions if llm else [])],
                "tool_errors": llm.tool_errors if llm else 0,
                "llm_status": llm.status if llm else None,
                "llm_unsupported": llm.verification.unsupported if llm and llm.verification else [],
                "fallback_model_used": bool(llm and llm.fallback_used),
            })
            print(f"{case['id']} r{repeat} ok={ok} path={result.answer_path} model={result.model_id} "
                  f"{runs[-1]['seconds']}s attempts={len(entries)} {reasons or ''}{claims or ''}", flush=True)
    total = len(runs)
    ok_runs = sum(r["ok"] for r in runs)
    llm_runs = [r for r in runs if r["answer_path"] == "llm_tools"]
    ok_entries = [e for e in ledger.entries if e.status == "ok" and e.latency_ms is not None]
    call_latency = sorted(e.latency_ms for e in ok_entries)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "kind": "live_online_path_evaluation",
        "strategy": "ai_first",
        "profile": {"mode": profile.mode, "primary": model, "fallbacks": fallbacks or [], "rpm": rpm,
                    "max_tool_iterations": profile.max_tool_iterations, "max_retries": profile.max_retries},
        "prompt_version": PROMPT_VERSION,
        "kb_version": catalog.kb.version,
        "runs": total,
        "ok": ok_runs,
        "accuracy": round(ok_runs / total, 4) if total else None,
        "answered_by_model": len(llm_runs),
        "model_answer_share": round(len(llm_runs) / total, 4) if total else None,
        "model_answers_ok": sum(r["ok"] for r in llm_runs),
        "fallbacks_to_deterministic": sum(1 for r in runs if r["answer_path"] == "fallback"),
        "verifier_rejections": sum(1 for r in runs if r["llm_status"] == "verifier_rejected"),
        "unsupported_claims_shown": sum(1 for r in runs if r["unsupported_shown_claims"]),
        "tool_errors": sum(r["tool_errors"] for r in runs),
        "model_calls": len(ledger.entries),
        "provider_errors": {k: sum(1 for e in ledger.entries if e.error_kind == k) for k in {e.error_kind for e in ledger.entries if e.error_kind}},
        "models_answered": sorted({e.model_id for e in ok_entries}),
        "tokens": {"input": sum(e.input_tokens or 0 for e in ledger.entries), "output": sum(e.output_tokens or 0 for e in ledger.entries),
                   "thought": sum(e.thought_tokens or 0 for e in ledger.entries)},
        "cost_usd_reported": str(sum((e.cost_usd for e in ledger.entries if e.cost_usd is not None), Decimal(0))),
        "calls_with_unknown_cost": sum(1 for e in ledger.entries if e.cost_usd is None),
        "turn_latency_ms": {"n": len(turn_latencies), "p50": round(statistics.median(turn_latencies), 1) if turn_latencies else None,
                            "p95": round(_p95(turn_latencies), 1) if turn_latencies else None},
        "model_call_latency_ms": {"n": len(call_latency), "p50": statistics.median(call_latency) if call_latency else None,
                                  "p95": _p95(call_latency) if call_latency else None},
        "results": runs,
    }
    label = name or model.replace(":", "_").replace("/", "_")
    (out / f"live_{label}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
