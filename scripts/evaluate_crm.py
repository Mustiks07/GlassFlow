"""Explicit offline evaluation. No runtime import of KEY or user pickle/joblib."""
import argparse
import csv
import hashlib
from pathlib import Path

from glassflow.modules.crm.evaluation import evaluate

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("inputs/PACK_for_teams/2_assistant_crm/applications_open.csv"))
    parser.add_argument("--output", type=Path, default=Path("docs/release/crm"))
    args = parser.parse_args()
    with args.input.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    report = evaluate(rows, args.output, hashlib.sha256(args.input.read_bytes()).hexdigest())
    for split in report["splits"]:
        print(split["split"], split.get("baseline_precision_at_25"), split.get("model_precision_at_25"))
    print("Frozen runtime policy: reference-v1; candidate not promoted")
