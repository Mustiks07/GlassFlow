"""CLI: ``uv run python -m glassflow.modules.intelligence.evaluation <command>``.

Commands:
  open       18 questions + 8 dialogs through the runtime, then the unmodified selfcheck.py
  extended   synthetic extended set (cases_extended.json), optional --repeats N
  perf       local quote / deterministic turn latency
  live       critical cases ×3 on the configured network profile (BLOCKED without a key)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from .runner import evaluate_extended, evaluate_open, measure_performance

ROOT = Path(__file__).resolve().parents[5]
CRITICAL = ["E026", "E027", "E028", "E031", "E038", "E053", "E054", "E065", "E069", "E072", "E079", "E080"]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="glassflow-intelligence-eval")
    parser.add_argument("command", choices=["open", "extended", "holdout", "perf", "live", "live-open"])
    parser.add_argument("--pack", type=Path, default=ROOT / "inputs" / "PACK_for_teams")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "ai" / "evidence")
    parser.add_argument("--allow-ai", action="store_true", help="use the configured network AI profile (counts quota)")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--model", default=None, help="live: provider:model_id, e.g. gemini:gemini-3.5-flash-lite")
    parser.add_argument("--fallbacks", default="", help="live: comma-separated provider:model_id")
    parser.add_argument("--cases", default="critical", help="live: critical | broad | comma-separated ids")
    parser.add_argument("--rpm", type=int, default=12)
    args = parser.parse_args()
    if args.command == "open":
        report = evaluate_open(args.pack, args.out / "open", allow_ai=args.allow_ai)
        summary = {k: report["selfcheck"][k]["stdout"] for k in ("assistant", "dialogs")}
    elif args.command == "extended":
        report = evaluate_extended(args.pack, args.out / "extended", allow_ai=args.allow_ai, repeats=args.repeats)
        summary = {k: report[k] for k in ("cases", "passed", "accuracy", "unconfirmed_commercial_claims", "groups",
                                          "answer_paths", "live_acceptance")}
    elif args.command == "holdout":
        report = evaluate_extended(
            args.pack, args.out / "holdout", allow_ai=args.allow_ai, repeats=args.repeats,
            cases_path=Path(__file__).with_name("cases_holdout.json"), name="holdout",
        )
        summary = {k: report[k] for k in ("cases", "passed", "accuracy", "unconfirmed_commercial_claims", "groups",
                                          "answer_paths", "live_acceptance")}
    elif args.command == "perf":
        report = measure_performance(args.pack, args.out / "perf")
        summary = {k: report[k] for k in ("quote_calculate_ms", "deterministic_turn_ms", "ai_turn_p95")}
    else:
        sys.exit(_live(args))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _live(args) -> int:
    """Live acceptance: exit 0 only for PASS; 3 for PARTIAL/FAIL; 2 for BLOCKED (no real model call)."""
    from .live import BROAD, LiveBlocked, evaluate_live, evaluate_open_live

    target = args.out / "live"
    target.mkdir(parents=True, exist_ok=True)
    fallbacks = [f for f in args.fallbacks.split(",") if f]
    try:
        if args.command == "live":
            ids = CRITICAL if args.cases == "critical" else BROAD if args.cases == "broad" else args.cases.split(",")
            report = evaluate_live(args.pack, target, model=args.model, fallbacks=fallbacks, case_ids=ids,
                                   repeats=args.repeats, rpm=args.rpm)
            keys = ("planned_runs", "runs", "stopped_early", "ok", "accuracy", "paths", "model_calls", "failed_calls",
                    "provider_errors", "models_answered", "tokens", "turn_latency_ms", "model_call_latency_ms", "preflight", "pacing")
        else:
            extra = ["E026", "E031", "E041", "E047", "E053", "E061", "E065", "E069", "E074", "E038", "H005", "H016"]
            report = evaluate_open_live(args.pack, target, model=args.model, fallbacks=fallbacks, rpm=args.rpm, extra_ids=extra)
            keys = ("paths", "latency_series_ms", "selected_model_call_latency_ms", "provider_errors", "models_answered",
                    "model_calls", "preflight")
    except LiveBlocked as exc:
        status = {
            "status": "BLOCKED",
            "command": args.command,
            "reason": exc.reason,
            "details": exc.details,
            "checked_at": datetime.now(UTC).isoformat(),
            "required": "a working provider key (or gateway URL + token) for the selected profile; no model call was made",
            "critical_cases": CRITICAL,
        }
        (target / "live_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 2
    summary = {"acceptance": report["acceptance"], **{k: report.get(k) for k in keys}}
    if args.command == "live-open":
        summary["selfcheck"] = report["selfcheck_assistant"]["stdout"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    status = report["acceptance"]["status"]
    return 0 if status == "PASS" else 2 if status == "BLOCKED" else 3


if __name__ == "__main__":
    main()
