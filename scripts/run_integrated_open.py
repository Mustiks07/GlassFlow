"""Run the actual HTTP application, download exact outputs and evaluate only afterwards.

No expected answers or solver fixtures enter the application. KEY access belongs
solely to the explicit post-run official evaluator in this script.
"""

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def changed_files():
    """Independent IDs and geometry, preserving meanings; no evaluation labels."""
    pack = ROOT / 'inputs/PACK_for_teams'
    files = []
    for relative, columns in (
        ('1_ostatki/stock_open.csv', ['remnant_id']),
        ('1_ostatki/orders_open.csv', ['part_id', 'order_id']),
        ('2_assistant_crm/applications_open.csv', ['app_id', 'client_id']),
        ('2_assistant_crm/questions_open.csv', ['id']),
        ('2_assistant_crm/dialogs_open.csv', ['id']),
    ):
        reader = csv.DictReader(io.StringIO((pack / relative).read_text(encoding='utf-8-sig')))
        headers = [c for c in reader.fieldnames if c != 'вернулся_за_60_дней']
        rows = list(reader)
        for row in rows:
            for column in columns:
                row[column] = 'NEW-' + row[column]
            row.pop('вернулся_за_60_дней', None)
            if 'длина_мм' in row:
                row['длина_мм'] = str(int(row['длина_мм']) + (7 if 'stock' in relative else 1))
        if 'questions' in relative:
            rows[0]['question'] = 'Сколько стоит стекло 6 мм прозрачное 451×370 мм с кромкой по всем сторонам?'
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=headers, lineterminator='\n')
        writer.writeheader()
        writer.writerows(reversed(rows))
        files.append(('files', (Path(relative).name, stream.getvalue().encode('utf-8'))))
    files.extend(('files', (Path(relative).name, (pack / relative).read_bytes())) for relative in (
        '1_ostatki/materials.csv', '2_assistant_crm/ksm_knowledge_base.json'))
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime/integrated-open")
    parser.add_argument("--budget", type=int, default=600)
    parser.add_argument("--profile", default="extended", choices=["quick", "standard", "extended"])
    parser.add_argument("--changed-inputs", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    start = time.monotonic()
    report = {"source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "kind": "actual_http_open_pack_run", "live_ai": "not_run", "profile": "local_limited"}
    with httpx.Client(base_url=args.base, timeout=120) as client:
        client.get("/api/v1/session").raise_for_status()
        def post(path, body=None, **kwargs):
            response = client.post("/api/v1" + path, json=body,
                headers={"Idempotency-Key": f"integration:{time.time_ns()}"}, **kwargs)
            response.raise_for_status()
            return response.json()
        if args.changed_inputs:
            preview = post('/imports/preview', files=changed_files())
            assert not preview['errors'], preview
            source = post(f"/imports/{preview['import_id']}/commit", {'name': 'New IDs and changed geometry without labels'})
            report['kind'] = 'actual_http_changed_input_run'
        else:
            source = post("/datasets/demo")
        buyer = post("/buyers/import", params={"dataset_id": source["dataset_id"]}, files={
            "file": ("buyers.platform.csv", (ROOT / "data/buyers/buyers.platform.csv").read_bytes(), "text/csv"),
            "evidence": ("evidence.platform.json", (ROOT / "data/buyers/evidence.platform.json").read_bytes(), "application/json")})
        if buyer["status"] != "verified":
            raise RuntimeError(f"Buyer structural validation failed: {buyer['errors']}")
        job = post("/runs", {"dataset_id": source["dataset_id"], "config_version": "integrated-v1",
            "modules": ["cutting", "assistant", "quality", "crm", "cards"],
            "solver_config": {"profile": args.profile, "seed": 42, "time_limit_seconds": args.budget,
                "workers": max(1, min(7, (os.cpu_count() or 1) - 1)), "minimum_free_remnants": 5},
            "ai_profile": "local_limited", "buyer_registry_version": buyer["version"]})
        report.update(run_id=job["run_id"], source_dataset_id=source["dataset_id"], buyer_registry=buyer)
        (args.output / "progress.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Started actual run {job['run_id']}", flush=True)
        last = None
        deadline = start + args.budget + 300
        while time.monotonic() < deadline:
            view = client.get(f"/api/v1/runs/{job['run_id']}").json()
            state = [(j["state"], j["stage"]) for j in view["jobs"]]
            if state != last:
                print(f"{time.monotonic() - start:.1f}s {view['status']} {state}", flush=True)
                last = state
            if view["status"] != "running":
                break
            time.sleep(1)
        else:
            raise RuntimeError("Run exceeded measured deadline")
        report["run_view"] = view
        exported = post(f"/runs/{job['run_id']}/export")
        report["export"] = exported
        downloaded = {}
        for name, url in exported["files"].items():
            response = client.get(url)
            response.raise_for_status()
            content = response.content
            (args.output / name).write_bytes(content)
            detail = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
            if name.endswith(".csv"):
                rows = list(csv.DictReader(io.StringIO(content.decode("utf-8"), newline=""), strict=True))
                detail.update(rows=len(rows), header=list(rows[0]) if rows else [], bom=content.startswith(b"\xef\xbb\xbf"))
            downloaded[name] = detail
        report["downloads"] = downloaded
    checks = {}
    pack = ROOT / "inputs/PACK_for_teams/2_assistant_crm"
    for mode, output, key in (("assistant", "answers.csv", "questions_open_KEY.csv"),
                              ("dialogs", "verdicts.csv", "dialogs_open_KEY.csv"),
                              ("crm", "picks.csv", "applications_open.csv")):
        if args.changed_inputs:
            checks[mode] = {'status': 'not_run', 'reason': 'Changed inputs have no official evaluation KEY'}
            continue
        if not (args.output / output).is_file():
            checks[mode] = {"status": "not_run", "reason": "output missing"}
            continue
        result = subprocess.run([sys.executable, "-X", "utf8", str(pack / "selfcheck.py"), mode,
            str(args.output / output), str(pack / key)], capture_output=True, encoding="utf-8", timeout=30)
        checks[mode] = {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
                        "validator_sha256": hashlib.sha256((pack / "selfcheck.py").read_bytes()).hexdigest()}
    report.update(official_open_evaluation=checks, duration_seconds=round(time.monotonic() - start, 3))
    (args.output / "integration-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"run_id": report["run_id"], "status": exported["status"], "errors": exported["errors"],
                      "duration_seconds": report["duration_seconds"], "evaluation": checks}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if exported["status"] == "ready" else 1)


if __name__ == "__main__":
    main()
