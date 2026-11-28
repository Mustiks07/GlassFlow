"""Reproduce preregistered A02 comparison on explicitly reused organizer open data."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from glassflow.modules.crm.competition import compete, write_report

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("inputs/PACK_for_teams/2_assistant_crm/applications_open.csv"))
    parser.add_argument("--protocol", type=Path, default=Path("docs/release/crm/A02_PROTOCOL.json"))
    parser.add_argument("--output", type=Path, default=Path("docs/release/crm/a02-comparison.json"))
    args = parser.parse_args()
    with args.input.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    report = compete(rows, json.loads(args.protocol.read_text(encoding="utf8")),
                     hashlib.sha256(args.input.read_bytes()).hexdigest(),
                     hashlib.sha256(args.protocol.read_bytes()).hexdigest())
    write_report(report, args.output)
    print(json.dumps(report["decision"], ensure_ascii=True, indent=2))
