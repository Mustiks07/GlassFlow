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
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ..assistant.local import TurnContext
from ..assistant.prompts import PROMPT_VERSION
from ..assistant.verifier import verify_answer
from ..providers.base import ChatMessage, ProviderError, ProviderRequest
from ..providers.policy import AIProfile, MemoryLedger, ModelRef, validate_profile
from ..providers.settings import AIRuntime, EnvSecrets, build_runtime, profile_from_env
from .runner import CASES_PATH, DATASET, _p95, build_environment, has_price_claim, numbers

CRITICAL = ["E026", "E027", "E028", "E031", "E038", "E053", "E054", "E065", "E069", "E072", "E079", "E080"]
BROAD = CRITICAL + ["E015", "E020", "E041", "E047", "E061", "E074", "E084", "H004", "H005", "H016", "H026", "H030"]


ACCEPTANCE_ACCURACY = 0.95
# Evaluation only: wait out a short breaker cooldown (per-minute limit, brief overload) before the
# next case instead of burning it on the deterministic fallback. A longer one (daily quota) stops
# the run; the remaining cases are reported as not run, never as passed.
LIVE_PACING_MAX_WAIT_S = 90.0


class LiveBlocked(Exception):
    """The selected live profile cannot make a real model call: NOT a live result."""

    def __init__(self, reason: str, details: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.details = details or {}


def prepare_live_runtime(model: str | None, fallbacks: list[str] | None, rpm: int, *, request_timeout_s: float = 45,
                         turn_deadline_s: float = 90) -> tuple[AIProfile, AIRuntime, MemoryLedger]:
    """Build the profile under test. Raises LiveBlocked before any network call if it cannot work."""
    if model:
        profile = AIProfile(name="live-eval", primary=_ref(model), fallbacks=[_ref(f) for f in (fallbacks or [])],
                            rpm=rpm, rpd=1000, turn_deadline_s=turn_deadline_s, request_timeout_s=request_timeout_s)
    else:
        profile = profile_from_env(secrets=EnvSecrets()).model_copy(update={"rpm": rpm})
    if profile.primary is None:
        raise LiveBlocked("profile_disabled", {"hint": "GLASSFLOW_AI_PROVIDER is none or no provider key is configured"})
    errors = validate_profile(profile)
    if errors:
        raise LiveBlocked("invalid_profile", {"errors": errors})
    ledger = MemoryLedger()
    runtime = build_runtime(profile, EnvSecrets(), prompt_version=PROMPT_VERSION, ledger=ledger)
    if not runtime.available:
        raise LiveBlocked(f"runtime_{runtime.status}", {"reason_ru": runtime.reason_ru})
    return profile, runtime, ledger


def preflight(runtime: AIRuntime) -> dict[str, object]:
    """One minimal real call through the selected chain; failure means BLOCKED, not a quality result."""
    assert runtime.client is not None
    started = time.monotonic()
    try:
        outcome = asyncio.run(runtime.client.call(
            ProviderRequest(system="Ответь одним словом: ok", messages=[ChatMessage(role="user", text="ping")],
                            max_output_tokens=16, purpose="settings_check"),
            deadline=time.monotonic() + 60,
        ))
    except ProviderError as exc:
        raise LiveBlocked(f"preflight_failed_{exc.kind}", {"message": str(exc)[:200]}) from None
    return {"ok": True, "model_id": outcome.response.model_id, "provider": outcome.response.provider,
            "latency_ms": int((time.monotonic() - started) * 1000), "attempts": outcome.attempts}


def _selected_models(runtime: AIRuntime) -> set[str]:
    refs = [r for r in [runtime.profile.primary, *runtime.profile.fallbacks] if r is not None]
    return {r.model_id for r in refs}


def acceptance(runs: list[dict], ok_calls: int, unsupported_shown: int, *, not_run: int = 0,
               stop_reason: str | None = None) -> dict[str, object]:
    """Live acceptance only counts answers that really came from the selected model."""
    online = [r for r in runs if r["answer_path"] == "llm_tools" and not r.get("cache_hit") and r.get("selected_model")]
    reasons: list[str] = []
    if ok_calls == 0 or not online:
        blocked = ["no confirmed call of the selected model"] + ([stop_reason] if stop_reason else [])
        return {"status": "BLOCKED", "reasons": blocked, "online_runs": 0, "online_accuracy": None, "not_run": not_run}
    online_ok = sum(r["ok"] for r in online)
    accuracy = online_ok / len(online)
    if any(r.get("cache_hit") for r in runs):
        reasons.append("cache hits in a live run")
    if unsupported_shown:
        reasons.append(f"{unsupported_shown} answers with unsupported claims")
    if accuracy < ACCEPTANCE_ACCURACY:
        reasons.append(f"online accuracy {accuracy:.3f} < {ACCEPTANCE_ACCURACY}")
    not_online = len(runs) - len(online)
    if reasons:
        status = "FAIL"
    elif not_online or not_run:
        status = "PARTIAL"
        if not_online:
            reasons.append(f"{not_online} of {len(runs)} runs were not answered by the selected model")
        if not_run:
            reasons.append(f"{not_run} planned runs not run: {stop_reason or 'stopped'}")
    else:
        status = "PASS"
    return {"status": status, "reasons": reasons, "online_runs": len(online), "online_ok": online_ok,
            "online_accuracy": round(accuracy, 4), "not_run": not_run}


def selected_cooldown_s(runtime: AIRuntime, selected: set[str]) -> float:
    """Seconds until a selected model leaves breaker cooldown (0 if one is usable now)."""
    client = runtime.client
    if client is None:
        return 0.0
    labels = [label for label in client.chain() if label.partition(":")[2] in selected]
    if not labels:
        return 0.0
    now = client.clock()
    return max(0.0, min(client.unhealthy_until.get(label, 0.0) - now for label in labels))


def _last_error(ledger: MemoryLedger) -> str:
    for entry in reversed(ledger.entries):
        if entry.status != "ok":
            return f"{entry.error_kind}: {(entry.error_message or '')[:120]}"
    return "none"


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


def _series(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "p50": None, "p95": None}
    return {"n": len(values), "p50": round(statistics.median(values), 1), "p95": round(_p95(values), 1)}


def evaluate_live(
    pack: Path,
    out: Path,
    *,
    model: str | None,
    fallbacks: list[str] | None = None,
    case_ids: list[str] | None = None,
    repeats: int = 1,
    rpm: int = 12,
    name: str | None = None,
    runtime_override: tuple[AIProfile, AIRuntime, MemoryLedger] | None = None,
    run_preflight: bool = True,
    pacing_max_wait_s: float = LIVE_PACING_MAX_WAIT_S,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Raises LiveBlocked (no report of quality) when the profile cannot make a real call."""
    out.mkdir(parents=True, exist_ok=True)
    env = build_environment(pack, allow_ai=False)
    profile, runtime, ledger = runtime_override or prepare_live_runtime(model, fallbacks, rpm)
    preflight_result = preflight(runtime) if run_preflight else {"ok": None, "skipped": True}
    preflight_calls = len(ledger.entries)
    selected = _selected_models(runtime)
    model = model or (profile.primary.label if profile.primary else "none")
    catalog = env.service.catalog_for(DATASET)
    engine = env.service._engine(catalog)
    engine.runtime = runtime
    engine.cache = type(engine.cache)(capacity=0)  # no answer cache in measurements
    runs = []
    turn_latencies = []
    label = name or model.replace(":", "_").replace("/", "_")
    progress = out / f"live_{label}.jsonl"  # incremental: an interrupted run keeps finished cases
    progress.write_text("", encoding="utf-8")
    planned = [(case, repeat) for case in _cases(case_ids or CRITICAL) for repeat in range(repeats)]
    pacing_waits: list[float] = []
    stop_reason: str | None = None
    for index, (case, repeat) in enumerate(planned):
        wait = selected_cooldown_s(runtime, selected)
        if wait > pacing_max_wait_s:
            stop_reason = (f"selected model unavailable for {wait:.0f} s (breaker after quota/overload; "
                           f"last error: {_last_error(ledger)})")
            print(f"stop: {stop_reason}; {len(planned) - index} runs not run", flush=True)
            break
        if wait > 0:
            pacing_waits.append(round(wait, 1))
            sleep(wait)
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
            "queue_ms": sum(e.queue_ms for e in entries),
            "provider_ms": sum(e.latency_ms or 0 for e in entries),
            "input_tokens": sum(e.input_tokens or 0 for e in entries), "output_tokens": sum(e.output_tokens or 0 for e in entries),
            "thought_tokens": sum(e.thought_tokens or 0 for e in entries),
            "tools": [(x.name, x.status) for x in (llm.executions if llm else [])],
            "tool_errors": llm.tool_errors if llm else 0,
            "llm_status": llm.status if llm else None,
            "llm_unsupported": llm.verification.unsupported if llm and llm.verification else [],
            "fallback_model_used": bool(llm and llm.fallback_used),
            "cache_hit": bool(result.cache_hit),
            "selected_model": bool(result.model_id) and any(m in (result.model_id or "") for m in selected),
        })
        with progress.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(runs[-1], ensure_ascii=False) + "\n")
        print(f"{case['id']} r{repeat} ok={ok} path={result.answer_path} model={result.model_id} "
              f"{runs[-1]['seconds']}s attempts={len(entries)} {reasons or ''}{claims or ''}", flush=True)
    total = len(runs)
    ok_runs = sum(r["ok"] for r in runs)
    llm_runs = [r for r in runs if r["answer_path"] == "llm_tools"]
    eval_entries = ledger.entries[preflight_calls:]
    ok_entries = [e for e in eval_entries if e.status == "ok" and e.latency_ms is not None and any(m in e.model_id for m in selected)]
    call_latency = sorted(e.latency_ms for e in ok_entries)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "kind": "live_online_path_evaluation",
        "strategy": "ai_first",
        "acceptance": acceptance(runs, len(ok_entries), sum(1 for r in runs if r["unsupported_shown_claims"]),
                                 not_run=len(planned) - len(runs), stop_reason=stop_reason),
        "preflight": preflight_result,
        "planned_runs": len(planned),
        "stopped_early": stop_reason,
        "pacing": {"max_wait_s": pacing_max_wait_s, "waits_s": pacing_waits,
                   "note": "evaluation waits out short breaker cooldowns; not counted in turn latency"},
        "selected_models": sorted(selected),
        "paths": {path: sum(1 for r in runs if r["answer_path"] == path) for path in ("llm_tools", "fallback", "deterministic")}
        | {"cache_hits": sum(1 for r in runs if r["cache_hit"])},
        "latency_basis": "model_call_latency_ms: successful calls of the selected models only; turn latency includes RPM queue",
        "failed_calls": sum(1 for e in eval_entries if e.status != "ok"),
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
        "model_calls": len(eval_entries),
        "provider_errors": {k: sum(1 for e in eval_entries if e.error_kind == k) for k in {e.error_kind for e in eval_entries if e.error_kind}},
        "models_answered": sorted({e.model_id for e in ok_entries}),
        "tokens": {"input": sum(e.input_tokens or 0 for e in ledger.entries), "output": sum(e.output_tokens or 0 for e in ledger.entries),
                   "thought": sum(e.thought_tokens or 0 for e in ledger.entries)},
        "cost_usd_reported": str(sum((e.cost_usd for e in ledger.entries if e.cost_usd is not None), Decimal(0))),
        "calls_with_unknown_cost": sum(1 for e in ledger.entries if e.cost_usd is None),
        "turn_latency_ms": {"n": len(turn_latencies), "p50": round(statistics.median(turn_latencies), 1) if turn_latencies else None,
                            "p95": round(_p95(turn_latencies), 1) if turn_latencies else None},
        "turn_latency_without_queue_ms": _series([r["seconds"] * 1000 - r["queue_ms"] for r in runs]),
        "queue_ms_total": sum(r["queue_ms"] for r in runs),
        "model_call_latency_ms": {"n": len(call_latency), "p50": statistics.median(call_latency) if call_latency else None,
                                  "p95": _p95(call_latency) if call_latency else None},
        "results": runs,
    }
    (out / f"live_{label}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def evaluate_open_live(
    pack: Path, out: Path, *, model: str | None, fallbacks: list[str] | None = None, rpm: int = 15,
    extra_ids: list[str] | None = None, runtime_override: tuple[AIProfile, AIRuntime, MemoryLedger] | None = None,
    run_preflight: bool = True,
    pacing_max_wait_s: float = LIVE_PACING_MAX_WAIT_S,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """The 18 open questions answered by the ONLINE path (ai_first), scored by the unmodified
    selfcheck.py; plus optional extra single-turn cases to complete a 30-request latency series."""
    from .runner import read_rows, run_selfcheck, write_csv

    out.mkdir(parents=True, exist_ok=True)
    env = build_environment(pack, allow_ai=False)
    profile, runtime, ledger = runtime_override or prepare_live_runtime(model, fallbacks, rpm, request_timeout_s=15, turn_deadline_s=60)
    preflight_result = preflight(runtime) if run_preflight else {"ok": None, "skipped": True}
    preflight_calls = len(ledger.entries)
    selected = _selected_models(runtime)
    engine = env.service._engine(env.service.catalog_for(DATASET))
    engine.runtime = runtime
    engine.cache = type(engine.cache)(capacity=0)
    questions = read_rows(pack / "2_assistant_crm" / "questions_open.csv")
    texts = [(q["id"], q["question"]) for q in questions] + [(c["id"], c["turns"][0]) for c in _cases(extra_ids or [])]
    rows, series = [], []
    pacing_waits: list[float] = []
    for qid, text in texts:
        wait = selected_cooldown_s(runtime, selected)
        if 0 < wait <= pacing_max_wait_s:  # short cooldown: wait; a daily quota is not waited for (answer -> PARTIAL)
            pacing_waits.append(round(wait, 1))
            sleep(wait)
        first = len(ledger.entries)
        started = time.monotonic()
        result = asyncio.run(engine.turn(text, TurnContext(), strategy="ai_first"))
        entries = ledger.entries[first:]
        elapsed = (time.monotonic() - started) * 1000
        series.append({"id": qid, "ms": round(elapsed), "queue_ms": sum(e.queue_ms for e in entries),
                       "path": result.answer_path, "model": result.model_id, "attempts": len(entries),
                       "errors": [e.error_kind for e in entries if e.status != "ok"]})
        rows.append((qid, result.answer, result.answer_path, result.verifier_status,
                     bool(result.model_id) and any(m in (result.model_id or "") for m in selected), bool(result.cache_hit)))
        print(f"{qid} {result.answer_path} {round(elapsed)}ms {result.model_id}", flush=True)
    open_rows = rows[: len(questions)]
    answers_csv = out / "answers_live.csv"
    write_csv(answers_csv, ["id", "answer"], [[row[0], row[1]] for row in open_rows])
    check = run_selfcheck(pack / "2_assistant_crm" / "selfcheck.py", "assistant", answers_csv, pack / "2_assistant_crm" / "questions_open_KEY.csv")
    total = [s["ms"] for s in series]
    eval_entries = ledger.entries[preflight_calls:]
    ok_selected = [e for e in eval_entries if e.status == "ok" and e.latency_ms is not None and any(m in e.model_id for m in selected)]
    online_open = [row for row in open_rows if row[2] == "llm_tools" and row[4] and not row[5]]
    score_ok = check.get("score") == 15.0 and "выдумок 0" in (check.get("stdout") or "")
    if not ok_selected or not online_open:
        status = "BLOCKED"
    elif len(online_open) < len(open_rows):
        status = "PARTIAL"
    else:
        status = "PASS" if score_ok else "FAIL"
    report = {
        "acceptance": {"status": status, "online_open_answers": len(online_open), "open_questions": len(open_rows),
                       "selfcheck_15_of_15_no_penalty": score_ok,
                       "note": "selfcheck is a pass only for the online path when every open answer came from the selected model"},
        "preflight": preflight_result,
        "selected_models": sorted(selected),
        "pacing": {"max_wait_s": pacing_max_wait_s, "waits_s": pacing_waits},
        "generated_at": datetime.now(UTC).isoformat(),
        "kind": "live_open_questions_ai_first",
        "profile": {"primary": model, "fallbacks": fallbacks or [], "rpm": rpm, "request_timeout_s": 15, "turn_deadline_s": 60},
        "prompt_version": PROMPT_VERSION,
        "selfcheck_assistant": check,
        "paths": {p: sum(1 for row in rows if row[2] == p) for p in {r[2] for r in rows}},
        "latency_series_ms": {**_series(total), "without_queue": _series([s["ms"] - s["queue_ms"] for s in series])},
        "model_calls": len(eval_entries),
        "selected_model_call_latency_ms": _series([e.latency_ms for e in ok_selected]),
        "provider_errors": {k: sum(1 for e in ledger.entries if e.error_kind == k) for k in {e.error_kind for e in ledger.entries if e.error_kind}},
        "models_answered": sorted({e.model_id for e in ledger.entries if e.status == "ok"}),
        "tokens": {"input": sum(e.input_tokens or 0 for e in ledger.entries), "output": sum(e.output_tokens or 0 for e in ledger.entries)},
        "series": series,
        "answers": [{"id": r[0], "answer": r[1], "path": r[2], "verifier": r[3], "selected_model": r[4], "cache_hit": r[5]} for r in rows],
    }
    label = (model or (profile.primary.label if profile.primary else "none")).replace(":", "_").replace("/", "_")
    (out / f"open_live_{label}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
