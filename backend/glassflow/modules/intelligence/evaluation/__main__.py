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
import os
from datetime import UTC, datetime
from pathlib import Path

from .runner import evaluate_extended, evaluate_open, measure_performance

ROOT = Path(__file__).resolve().parents[5]
CRITICAL = ["E026", "E027", "E028", "E031", "E038", "E053", "E054", "E065", "E069", "E072", "E079", "E080"]


def main() -> None:
    parser = argparse.ArgumentParser(prog="glassflow-intelligence-eval")
    parser.add_argument("command", choices=["open", "extended", "holdout", "perf", "live"])
    parser.add_argument("--pack", type=Path, default=ROOT / "inputs" / "PACK_for_teams")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "ai" / "evidence")
    parser.add_argument("--allow-ai", action="store_true", help="use the configured network AI profile (counts quota)")
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    if args.command == "open":
        report = evaluate_open(args.pack, args.out / "open", allow_ai=args.allow_ai)
        summary = {k: report["selfcheck"][k]["stdout"] for k in ("assistant", "dialogs")}
    elif args.command == "extended":
        report = evaluate_extended(args.pack, args.out / "extended", allow_ai=args.allow_ai, repeats=args.repeats)
        summary = {k: report[k] for k in ("cases", "passed", "accuracy", "unconfirmed_commercial_claims", "groups")}
    elif args.command == "holdout":
        report = evaluate_extended(
            args.pack, args.out / "holdout", allow_ai=args.allow_ai, repeats=args.repeats,
            cases_path=Path(__file__).with_name("cases_holdout.json"), name="holdout",
        )
        summary = {k: report[k] for k in ("cases", "passed", "accuracy", "unconfirmed_commercial_claims", "groups")}
    elif args.command == "perf":
        report = measure_performance(args.pack, args.out / "perf")
        summary = {k: report[k] for k in ("quote_calculate_ms", "deterministic_turn_ms", "ai_turn_p95")}
    else:
        has_key = any(os.environ.get(name) for name in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "GLASSFLOW_GATEWAY_TOKEN"))
        target = args.out / "live"
        target.mkdir(parents=True, exist_ok=True)
        if not has_key:
            summary = {
                "status": "BLOCKED",
                "reason": "No GEMINI_API_KEY / OPENROUTER_API_KEY / GLASSFLOW_GATEWAY_TOKEN in this environment.",
                "required": "Set a free-tier key (or gateway URL+token) and rerun: "
                            "uv run python -m glassflow.modules.intelligence.evaluation live",
                "checked_at": datetime.now(UTC).isoformat(),
                "critical_cases": CRITICAL,
            }
            (target / "live_status.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            report = evaluate_extended(args.pack, target, allow_ai=True, repeats=3)
            summary = {k: report[k] for k in ("cases", "passed", "accuracy", "unconfirmed_commercial_claims", "latency_ms", "ai")}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
