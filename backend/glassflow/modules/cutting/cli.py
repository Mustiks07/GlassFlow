"""Cutting evidence and developer CLI.

    uv run python -m glassflow.modules.cutting.cli solve --pack inputs/PACK_for_teams/1_ostatki \
        --profile extended --time 600 --out .runtime/cutting/solution.csv --evidence .runtime/cutting/evidence.json

    uv run python -m glassflow.modules.cutting.cli seed-db --pack inputs/PACK_for_teams/1_ostatki \
        --dataset-id open-workspace --mode workspace

``solve`` runs the product engine (not research scripts, never reading research CSVs), writes an exact
solution.csv and runs the UNMODIFIED organisers' validate.py in a subprocess with explicit UTF-8,
saving stdout/stderr/exit code with config, seed, runtime, input hashes and the git commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from glassflow.contracts.cutting import SolverConfig

from .conversion import input_from_snapshot
from .engine import CuttingEngine, default_workers
from .source_io import load_pack, solution_rows, write_solution_csv

ROOT = Path(__file__).resolve().parents[4]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(["git", "status", "--porcelain", "backend"], cwd=ROOT, capture_output=True, text=True,
                               timeout=10).stdout.strip()
        return out.stdout.strip() + ("+dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


class _Progress:
    def __init__(self, quiet: bool):
        self.quiet = quiet
        self.incumbents: list[dict] = []
        self.started = time.perf_counter()

    def cancelled(self) -> bool:
        return False

    def progress(self, stage, completed, total) -> None:
        return None

    def incumbent(self, plan) -> None:
        record = {"t": round(time.perf_counter() - self.started, 3), "coverage_percent": plan.metrics.coverage_percent,
                  "stage": plan.evidence.get("stage"), "valid": plan.status == "validated"}
        self.incumbents.append(record)
        if not self.quiet:
            print(f"  incumbent t={record['t']}s coverage={record['coverage_percent']}% ({record['stage']})", flush=True)


def run_official(validator: Path, stock: Path, orders: Path, solution: Path, materials: Path) -> dict:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = subprocess.run([sys.executable, "-X", "utf8", str(validator), str(stock), str(orders), str(solution),
                           str(materials)], capture_output=True, text=True, encoding="utf-8", env=env, timeout=300)
    result = {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT "):
            result["result_line"] = line
            for token in line.split()[1:]:
                key, _, value = token.partition("=")
                result[key] = value
    return result


def cmd_solve(args) -> int:
    pack = Path(args.pack)
    stock, orders, materials = pack / args.stock, pack / args.orders, pack / args.materials
    snapshot = load_pack(pack, args.stock, args.orders, args.materials, dataset_id=args.dataset_id)
    config = SolverConfig(profile=args.profile, seed=args.seed, time_limit_seconds=args.time,
                          workers=args.workers or default_workers(), minimum_free_remnants=args.min_free,
                          fixed_work=args.fixed_work)
    progress = _Progress(args.quiet)
    started = time.perf_counter()
    plan = CuttingEngine().solve(input_from_snapshot(snapshot, config=config), progress)
    wall = time.perf_counter() - started
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    assignments = {p.part_id: p for p in plan.placements}
    write_solution_csv(out, solution_rows(snapshot, assignments))
    validator = Path(args.validator) if args.validator else pack / "validate.py"
    official = run_official(validator, stock, orders, out, materials) if validator.exists() else {"exit_code": None,
                                                                                                "missing": str(validator)}
    m = plan.metrics
    evidence = {
        "generated_at": datetime.now(UTC).isoformat(),
        "kind": "product engine run (not research output)",
        "git_commit": git_commit(),
        "config": config.model_dump(),
        "inputs": {p.name: sha256(p) for p in (stock, orders, materials)},
        "validator": {"path": str(validator), "sha256": sha256(validator) if validator.exists() else None,
                      **official},
        "solution": {"path": str(out), "sha256": sha256(out)},
        "wall_seconds": round(wall, 3),
        "plan_status": plan.status,
        "search_status": plan.search_status,
        "stop_reason": plan.stop_reason,
        "metrics": m.model_dump(mode="json", exclude={"new_reasons"}),
        "new_reason_counts": {code: list(m.new_reasons.values()).count(code) for code in sorted(set(m.new_reasons.values()))},
        "free_original_remnant_ids": plan.free_original_remnant_ids,
        "internal_issues": [i.model_dump() for i in plan.issues],
        "engine_evidence": plan.evidence,
        "incumbents": progress.incumbents,
    }
    if args.evidence:
        path = Path(args.evidence)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"coverage={m.coverage_percent}% covered_area_mm2={m.covered_area_mm2} parts={m.covered_parts}/"
          f"{m.total_parts} used_remnants={m.used_remnants} free_original={m.free_original_remnants} "
          f"orders_full={m.fully_covered_orders} value_tg={m.replacement_value_tg} invalid={m.invalid} "
          f"missing={m.missing} status={plan.search_status}/{plan.stop_reason} wall={wall:.1f}s")
    print("official:", official.get("result_line"), "exit", official.get("exit_code"))
    ok = plan.status == "validated" and official.get("exit_code") == 0 and official.get("invalid") == "0"
    return 0 if ok else 1


def cmd_seed(args) -> int:
    from glassflow.core.db import create_database

    from .service import CuttingService
    from .uow import write_transaction

    snapshot = load_pack(Path(args.pack), args.stock, args.orders, args.materials, dataset_id=args.dataset_id)
    engine, factory = create_database(Path(args.data_dir) if args.data_dir else None)
    try:
        with write_transaction(factory) as session:
            CuttingService(session, actor="cli").register_dataset(args.dataset_id, args.mode, snapshot)
    finally:
        engine.dispose()
    print(f"registered {args.dataset_id} ({args.mode}): {len(snapshot.remnants)} remnants, {len(snapshot.parts)} parts")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="glassflow-cutting")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("solve", "seed-db"):
        p = sub.add_parser(name)
        p.add_argument("--pack", required=True)
        p.add_argument("--stock", default="stock_open.csv")
        p.add_argument("--orders", default="orders_open.csv")
        p.add_argument("--materials", default="materials.csv")
        p.add_argument("--dataset-id", default="open-pack")
    s = sub.choices["solve"]
    s.add_argument("--profile", choices=["quick", "standard", "extended"], default="extended")
    s.add_argument("--time", type=int, default=600)
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--workers", type=int, default=0)
    s.add_argument("--min-free", type=int, default=5)
    s.add_argument("--fixed-work", action="store_true")
    s.add_argument("--out", default=".runtime/cutting/solution.csv")
    s.add_argument("--evidence", default=".runtime/cutting/evidence.json")
    s.add_argument("--validator", default="")
    s.add_argument("--quiet", action="store_true")
    d = sub.choices["seed-db"]
    d.add_argument("--mode", choices=["source", "workspace", "contest"], default="workspace")
    d.add_argument("--data-dir", default="")
    args = parser.parse_args(argv)
    return cmd_solve(args) if args.command == "solve" else cmd_seed(args)


if __name__ == "__main__":
    raise SystemExit(main())
