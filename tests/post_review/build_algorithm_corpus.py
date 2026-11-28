"""Preregistered synthetic algorithm stress inputs; not a hidden-pack score predictor."""

import copy
import csv
import hashlib
import io
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "inputs/PACK_for_teams/1_ostatki"


def table(name):
    reader = csv.DictReader(io.StringIO((PACK / name).read_text(encoding="utf-8-sig")))
    return reader.fieldnames, list(reader)


def encoded(headers, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def main():
    sh, source_stock = table("stock_open.csv")
    oh, source_orders = table("orders_open.csv")
    material = (PACK / "materials.csv").read_text(encoding="utf-8-sig")
    cases = []
    for family in ["renamed_permuted", "scarce_oversize", "tempered_defect", "materials_locations"]:
        for seed in [17, 43, 101]:
            rng = random.Random(seed)
            stock, orders = copy.deepcopy(source_stock), copy.deepcopy(source_orders)
            eligible = []
            for index, row in enumerate(stock):
                row["remnant_id"] = f"IR-{seed}-" + row["remnant_id"]
                if family == "scarce_oversize" and index % 3 == 0:
                    row["длина_мм"] = str(max(20, int(row["длина_мм"]) // 2))
                if family == "tempered_defect":
                    if index % 4 == 0:
                        row["дефект"] = "1"
                    if row["material_id"].startswith("temp-"):
                        row["длина_мм"] = str(int(row["длина_мм"]) + 3)
                if family == "materials_locations":
                    row["место"] = f"Испытательный стеллаж {index % 7}, ячейка {index % 3}"
                if (
                    row["material_id"] in {"clear-4", "clear-6"}
                    and row["дефект"] == "0"
                    and len(eligible) < 8
                ):
                    eligible.append(row["remnant_id"])
            for index, row in enumerate(orders):
                row["part_id"] = f"IR-{seed}-" + row["part_id"]
                row["order_id"] = f"IR-{seed}-" + row["order_id"]
                if family == "scarce_oversize" and index % 7 == 0:
                    row["длина_мм"] = "5001"
                if family == "tempered_defect" and index % 5 == 0:
                    row["премиум"] = "1"
            rng.shuffle(stock)
            rng.shuffle(orders)
            inputs = {
                "materials.csv": material,
                "stock.csv": encoded(sh, stock),
                "orders.csv": encoded(oh, orders),
            }
            cases.append(
                {
                    "id": f"{family}-{seed}",
                    "family": family,
                    "seed": seed,
                    "inputs_csv": inputs,
                    "sha256": {
                        name: hashlib.sha256(text.encode("utf8")).hexdigest() for name, text in inputs.items()
                    },
                    "synthetic_eligible_set_for_N01_helper_only": eligible,
                }
            )
    document = {
        "schema_version": 1,
        "frozen_before_candidate_results": True,
        "source_baseline_commit": "5648852d64189ffd7269c277002f6fbc40c8039a",
        "policy": "All synthetic TEST variants reported; reused open-pack physics is not an independent hidden holdout. Eligibility vector is a domain fixture, not public buyer evidence.",
        "paired_budget": {
            "profile": "standard",
            "time_limit_seconds": 10,
            "workers": 1,
            "peak_memory_cap_bytes": 2147483648,
            "measure_all_runs_not_best_seed_only": True,
        },
        "promotion": {
            "invalid": 0,
            "missing": 0,
            "same_budget_threads_memory": True,
            "report_all_deltas": True,
            "baseline_kept_if_no_measured_gain": True,
            "pool_optimum_not_global": True,
            "location_tie_break_must_preserve_area_and_full_orders": True,
        },
        "cases": cases,
    }
    Path(__file__).with_name("algorithm_corpus_v1.json").write_bytes(
        (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf8")
    )
    print(f"Preregistered {len(cases)} paired algorithm cases")


if __name__ == "__main__":
    main()
