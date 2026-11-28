"""Execute every preregistered cutting case through real HTTP and official validator."""

import argparse
import csv
import hashlib
import io
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--ids", nargs="*")
    p.add_argument(
        "--normalize-stock-sides",
        action="store_true",
        help="Separate labelled derivative, never overwrite frozen corpus",
    )
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    frozen = (ROOT / "tests/post_review/algorithm_corpus_v1.json").read_bytes()
    corpus = json.loads(frozen)
    report = {
        "candidate": args.candidate,
        "corpus_sha256": hashlib.sha256(frozen).hexdigest(),
        "kind": "SYNTHETIC independent preregistered inputs; actual HTTP/solver/official geometry validator",
        "results": [],
        "stock_side_normalization_derivative": args.normalize_stock_sides,
    }
    report_path = args.out / "report.json"
    if args.resume and report_path.is_file():
        prior = json.loads(report_path.read_text(encoding="utf8"))
        if prior["corpus_sha256"] != report["corpus_sha256"] or prior["candidate"] != args.candidate:
            raise RuntimeError("Cannot resume changed corpus/candidate")
        report = prior
    pack = ROOT / "inputs/PACK_for_teams"
    validator = pack / "1_ostatki/validate.py"
    with httpx.Client(base_url=args.base, timeout=120) as c:
        c.get("/api/v1/session").raise_for_status()

        def post(path, body=None, **kwargs):
            response = c.post(
                "/api/v1" + path,
                json=body,
                headers={"Idempotency-Key": f"review-cutting:{time.time_ns()}"},
                **kwargs,
            )
            response.raise_for_status()
            return response.json()

        for case in corpus["cases"]:
            if args.ids and case["id"] not in args.ids:
                continue
            if any(row["case_id"] == case["id"] for row in report["results"]):
                continue
            output = args.out / case["id"]
            output.mkdir(exist_ok=True)
            files = []
            names = {
                "stock.csv": "stock_open.csv",
                "orders.csv": "orders_open.csv",
                "materials.csv": "materials.csv",
            }
            for name, content in case["inputs_csv"].items():
                if args.normalize_stock_sides and name == "stock.csv":
                    reader = csv.DictReader(io.StringIO(content))
                    rows = list(reader)
                    for row in rows:
                        length, width = int(row["длина_мм"]), int(row["ширина_мм"])
                        row["длина_мм"], row["ширина_мм"] = str(max(length, width)), str(min(length, width))
                    stream = io.StringIO(newline="")
                    writer = csv.DictWriter(stream, fieldnames=reader.fieldnames, lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(rows)
                    content = stream.getvalue()
                (output / name).write_bytes(content.encode())
                files.append(("files", (names[name], content.encode())))
            for relative in [
                "applications_open.csv",
                "questions_open.csv",
                "dialogs_open.csv",
                "ksm_knowledge_base.json",
            ]:
                files.append(("files", (relative, (pack / "2_assistant_crm" / relative).read_bytes())))
            preview = post("/imports/preview", files=files)
            if preview["errors"]:
                report["results"].append(
                    {
                        "case_id": case["id"],
                        "family": case["family"],
                        "seed": case["seed"],
                        "ok": False,
                        "status": "INPUT_REJECTED_REVIEWER_CORPUS",
                        "preview": preview,
                        "interpretation": "Frozen synthetic corpus rejected at documented import boundary; no solver result or candidate defect inferred. Preserve raw input; any normalized derivative must be separately labelled.",
                    }
                )
                report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
                print(case["id"], "INPUT_REJECTED_REVIEWER_CORPUS", flush=True)
                continue
            source = post(f"/imports/{preview['import_id']}/commit", {"name": "SYNTHETIC " + case["id"]})
            workspace = post(f"/datasets/{source['dataset_id']}/working-copy", {})
            d = workspace["dataset_id"]
            started = time.perf_counter()
            job = post(
                "/cutting/solve",
                {
                    "dataset_id": d,
                    "config": {
                        "profile": corpus["paired_budget"]["profile"],
                        "seed": case["seed"],
                        "time_limit_seconds": corpus["paired_budget"]["time_limit_seconds"],
                        "workers": 1,
                        "minimum_free_remnants": 5,
                    },
                },
            )
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                job = c.get(f"/api/v1/jobs/{job['job_id']}").json()
                if job["state"] in {"completed", "failed", "cancelled", "interrupted"}:
                    break
                time.sleep(0.1)
            row = {
                "case_id": case["id"],
                "family": case["family"],
                "seed": case["seed"],
                "job": job,
                "HTTP_job_elapsed_seconds": round(time.perf_counter() - started, 3),
            }
            if job["state"] == "completed":
                plan = job["result"]
                response = c.get(f"/api/v1/plans/{plan['plan_id']}/export", params={"dataset_id": d})
                response.raise_for_status()
                (output / "solution.csv").write_bytes(response.content)
                checked = subprocess.run(
                    [
                        sys.executable,
                        "-X",
                        "utf8",
                        str(validator),
                        str(output / "stock.csv"),
                        str(output / "orders.csv"),
                        str(output / "solution.csv"),
                        str(output / "materials.csv"),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf8",
                    timeout=30,
                )
                row["official_validator"] = {
                    "exit_code": checked.returncode,
                    "stdout": checked.stdout,
                    "stderr": checked.stderr,
                }
                row["ok"] = (
                    checked.returncode == 0
                    and plan["metrics"]["invalid"] == 0
                    and plan["metrics"]["missing"] == 0
                )
            else:
                row["ok"] = False
            report["results"].append(row)
            (args.out / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
            )
            print(case["id"], row["ok"], flush=True)
    print(
        json.dumps(
            {"total": len(report["results"]), "valid": sum(r["ok"] for r in report["results"])}, indent=2
        )
    )


if __name__ == "__main__":
    main()
