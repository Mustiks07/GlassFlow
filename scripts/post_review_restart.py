"""Hard app restart and durable row reuse via actual HTTP, without model calls."""

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--python", type=Path, required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--port", type=int, default=18177)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = {
        "candidate": args.candidate,
        "kind": "SYNTHETIC 1000 question IDs; real app process kill/restart/HTTP/SQLite",
        "status": "NOT_RUN",
    }
    env = os.environ.copy()
    env["GLASSFLOW_DATA_DIR"] = str((args.out / "data").resolve())
    env["PYTHONPATH"] = str((args.source / "backend").resolve())
    source_hashes = {
        p.relative_to(args.source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((args.source / "backend").rglob("*.py"))
    }
    # Standard artifact build metadata prevents Git from finding our enclosing review repository.
    stamp = args.source / "glassflow/build-info.json"
    stamp.parent.mkdir(exist_ok=True)
    stamp.write_text(
        json.dumps(
            {
                "commit": args.candidate,
                "source_digest": hashlib.sha256(
                    json.dumps(source_hashes, sort_keys=True).encode()
                ).hexdigest(),
                "frozen": False,
            }
        ),
        encoding="utf8",
    )
    report["source_digest"] = json.loads(stamp.read_text())["source_digest"]
    log = (args.out / "server.log").open("a", encoding="utf8")
    processes = []

    def launch():
        process = subprocess.Popen(
            [
                str(args.python),
                "-m",
                "uvicorn",
                "glassflow.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
                "--no-access-log",
            ],
            cwd=args.source,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        processes.append(process)
        for _ in range(100):
            try:
                if httpx.get(f"http://127.0.0.1:{args.port}/api/v1/ready", timeout=0.5).status_code == 200:
                    return process
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise RuntimeError("Review app did not start")

    try:
        process = launch()
        with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=120) as c:
            c.get("/api/v1/session").raise_for_status()
            pack = ROOT / "inputs/PACK_for_teams"
            output = io.StringIO(newline="")
            writer = csv.writer(output, lineterminator="\n")
            writer.writerow(["id", "question"])
            for n in range(1000):
                writer.writerow(
                    [
                        f"TEST-RESTART-{n:04}",
                        "Сколько стоит прозрачное стекло 6 мм 417×389 мм, 1 шт., без обработки?",
                    ]
                )
            paths = [
                "1_ostatki/materials.csv",
                "1_ostatki/stock_open.csv",
                "1_ostatki/orders_open.csv",
                "2_assistant_crm/applications_open.csv",
                "2_assistant_crm/questions_open.csv",
                "2_assistant_crm/dialogs_open.csv",
                "2_assistant_crm/ksm_knowledge_base.json",
            ]
            files = [
                (
                    "files",
                    (
                        Path(name).name,
                        output.getvalue().encode()
                        if Path(name).name == "questions_open.csv"
                        else (pack / name).read_bytes(),
                    ),
                )
                for name in paths
            ]

            def post(path, body=None, **kwargs):
                r = c.post(
                    "/api/v1" + path,
                    json=body,
                    headers={"Idempotency-Key": f"review-restart:{time.time_ns()}"},
                    **kwargs,
                )
                r.raise_for_status()
                return r.json()

            preview = post("/imports/preview", files=files)
            assert not preview["errors"], preview
            source = post(
                f"/imports/{preview['import_id']}/commit", {"name": "SYNTHETIC restart 1000 rows, no model"}
            )
            run = post(
                "/runs",
                {
                    "dataset_id": source["dataset_id"],
                    "modules": ["assistant"],
                    "config_version": "review-restart",
                    "ai_profile": "local_limited",
                    "total_budget_seconds": 180,
                    "export_reserve_seconds": 5,
                },
            )
            rid = run["run_id"]
            report["run_id"] = rid
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                view = c.get(f"/api/v1/runs/{rid}").json()
                job = view["jobs"][0]
                if 1 <= job["accepted_row_count"] < 1000:
                    break
                time.sleep(0.03)
            else:
                raise RuntimeError(
                    "Did not observe a partial accepted checkpoint before deadline; no restart PASS"
                )
            report["before_hard_kill"] = job
            process.kill()
            process.wait(timeout=10)
            process = launch()
            c.cookies.clear()
            c.get("/api/v1/session").raise_for_status()
            current = c.get(f"/api/v1/runs/{rid}").json()
            report["after_restart"] = current
            retried = post(f"/jobs/{job['job_id']}/retry", params={"dataset_id": job["dataset_id"]})
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                after = c.get(f"/api/v1/jobs/{retried['job_id']}").json()
                if after["state"] in {"completed", "failed", "cancelled", "interrupted"}:
                    break
                time.sleep(0.1)
            report["retried"] = after
            paths = (after.get("result") or {}).get("provenance", {}).get("answer_paths", [])
            reused = [row for row in paths if row.get("path") == "checkpoint_reuse" and row.get("resumed")]
            usage = c.get("/api/v1/assistant/usage").json()
            report["reuse_count"] = len(reused)
            report["provider_calls"] = usage["calls"]
            report["status"] = (
                "PASS_BOUNDARY_NOT_LIVE_ACCEPTANCE"
                if after["state"] == "completed"
                and len(reused) >= job["accepted_row_count"]
                and len(paths) == 1000
                and usage["calls"] == 0
                else "FAIL_OR_PARTIAL"
            )
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        log.close()
        (args.out / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
        )
    print(json.dumps({k: report.get(k) for k in ("status", "reuse_count", "provider_calls")}, indent=2))


if __name__ == "__main__":
    main()
