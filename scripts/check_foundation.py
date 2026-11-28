"""Check source integrity and assignment completeness. Not product acceptance."""

import argparse
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--runtime-source", action="store_true", help="Release code omits evaluation-only KEY")
args = parser.parse_args()
manifest = json.loads((root / "docs/specification/input_manifest.json").read_text(encoding="utf-8"))
verified = 0
for name, record in manifest.items():
    path = root / name.replace("\\", "/")
    if args.runtime_source and "_KEY." in path.name and not path.exists():
        continue
    assert path.stat().st_size == record["bytes"], name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"], name
    verified += 1

coverage = json.loads((root / "docs/agents/coverage.json").read_text(encoding="utf-8"))
for key, prefix, count in [("requirements", "R", 66), ("tests", "T", 67)]:
    rows = coverage[key]
    assert len(rows) == count, key
    assert {row["id"] for row in rows} == {f"{prefix}{i:02d}" for i in range(1, count + 1)}, key
    assert all(row["owner"] in {"claude1", "claude2", "claude3", "gptpro"} for row in rows)

pdf = root / "docs/specification/GlassFlow_Development_Specification_v1.pdf"
assert (
    hashlib.sha256(pdf.read_bytes()).hexdigest()
    == "8c12555bb82f906dab1d83413f5569a2d4abeacb0f8f00dd254763683cc8cd3f"
)
print(
    f"PASS: {verified} immutable inputs; 66 requirements; 67 assigned acceptance scenarios; exact specification PDF"
)
