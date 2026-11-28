"""Small author-owned N04 baseline comparison, not the independent AI exam.

Run baseline and candidate in separate processes; baseline reloads only changed
matching/local files from the pinned immutable commit. No evaluator keys or oracle.
"""

from __future__ import annotations

import argparse
import importlib
import json
import statistics
import subprocess
import time
from pathlib import Path

BASELINE = "5648852d64189ffd7269c277002f6fbc40c8039a"
CASES = [
    ("complete_mm", "Стекло 6 мм прозрачное 450×370 мм, 1 шт., евро-кромка по всем сторонам", "answered", "1988.00"),
    ("complete_cm", "Стекло 6 мм прозрачное 45×37 см, 1 шт., евро-кромка по всем сторонам", "answered", "1988.00"),
    ("complete_m", "Стекло 6 мм прозрачное 0,45×0,37 м, 1 шт., евро-кромка по всем сторонам", "answered", "1988.00"),
    ("edge_choice", "Стекло 6 мм прозрачное 450×370 мм, 2 шт., кромка по выбранным сторонам", "clarification", None),
    ("sensor_choice", "Нужен сенсорный переключатель для зеркала, сколько за 3 шт?", "clarification", None),
    ("manager_price_complete", "Рифленое прозрачное 8 мм, деталь 400×300 мм, 2 шт., сколько стоит?", "manager_handoff", None),
    ("manager_rate", "Рифленое прозрачное 8 мм за квадратный метр", "manager_handoff", None),
    ("implicit_mm", "Стекло 6 мм прозрачное 45×37, кромка по всем сторонам", "answered", "78.92"),
    ("unknown_dimension_unit", "Стекло 6 мм прозрачное 0,45×0,37, кромка по всем сторонам", "clarification", None),
]


def run(baseline=False):
    if baseline:
        for name in ("catalog.matching", "assistant.local"):
            module = importlib.import_module(f"glassflow.modules.intelligence.{name}")
            relative = "backend/glassflow/modules/intelligence/" + name.replace(".", "/") + ".py"
            original = subprocess.run(["git", "show", f"{BASELINE}:{relative}"], check=True, capture_output=True).stdout
            exec(compile(original, f"baseline:{relative}", "exec"), module.__dict__)
    from ..assistant.local import LocalEngine
    from ..catalog.kb import parse_knowledge_base
    from ..catalog.mapping import derive_all
    from ..catalog.materials import parse_materials
    root = Path(__file__).resolve().parents[5]
    pack = root / "inputs" / "PACK_for_teams"
    kb = parse_knowledge_base((pack / "2_assistant_crm" / "ksm_knowledge_base.json").read_bytes())
    materials = parse_materials((pack / "1_ostatki" / "materials.csv").read_bytes())
    engine = LocalEngine(kb, derive_all(kb, materials), dataset_id="author-comparison")
    rows, timings = [], []
    for case_id, text, expected_status, expected_total in CASES:
        for _ in range(30):
            started = time.perf_counter()
            result = engine.respond(text, inventory_mode="none")
            timings.append((time.perf_counter() - started) * 1000)
        total = str(result.pricing.total) if result.pricing and result.pricing.total is not None else None
        rows.append({"id": case_id, "question": text, "status": result.status,
            "correct_status": result.status == expected_status,
            "correct_total": total == expected_total if expected_total is not None else None,
            "clarification": result.clarification, "missing_parameters": result.missing_parameters,
            "unnecessary_parameter_request": "manager_" in case_id and "уточните" in result.answer.lower(),
            "answer": result.answer})
    return {"label": "author_regression_comparison_not_independent_acceptance", "baseline": baseline,
        "baseline_commit": BASELINE, "cases": rows,
        "metrics": {"cases": len(rows), "correct_status": sum(r["correct_status"] for r in rows),
            "complete_correct_totals": sum(r["correct_total"] is True for r in rows),
            "unnecessary_manager_parameter_requests": sum(r["unnecessary_parameter_request"] for r in rows),
            "clarification_count": sum(r["clarification"] is not None for r in rows),
            "latency_median_ms": statistics.median(timings), "latency_p95_ms": sorted(timings)[int(len(timings) * .95) - 1],
            "provider_calls": 0}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.baseline)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=True))
