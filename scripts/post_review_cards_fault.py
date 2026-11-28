"""Real empty-eligibility cards failure, repeated ticks and two actual app restarts."""

import argparse
import hashlib
import json
import os
import sqlite3
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
    p.add_argument("--port", type=int, default=18179)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["GLASSFLOW_DATA_DIR"] = str((args.out / "data").resolve())
    env["PYTHONPATH"] = str((args.source / "backend").resolve())
    report = {
        "candidate": args.candidate,
        "kind": "Real HTTP/process/DB; SYNTHETIC empty application evidence creates intentional cards failure, not a buyer demand claim",
        "observations": [],
        "status": "NOT_RUN_OR_INCOMPLETE",
    }
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
        raise RuntimeError("Fault review app did not start")

    try:
        process = launch()
        with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=120) as c:
            c.get("/api/v1/session").raise_for_status()

            def post(path, body=None, **kwargs):
                r = c.post(
                    "/api/v1" + path,
                    json=body,
                    headers={"Idempotency-Key": f"review-cards-fault:{time.time_ns()}"},
                    **kwargs,
                )
                r.raise_for_status()
                return r.json()

            source = post("/datasets/demo")
            evidence = json.loads(
                (ROOT / "data/buyers/evidence.independent-v2.json").read_text(encoding="utf8")
            )
            for row in evidence["records"]:
                row["applications"] = []
            buyer = post(
                "/buyers/import",
                params={"dataset_id": source["dataset_id"]},
                files={
                    "file": (
                        "buyers.csv",
                        (ROOT / "data/buyers/buyers.independent-v2.csv").read_bytes(),
                        "text/csv",
                    ),
                    "evidence": (
                        "evidence.json",
                        json.dumps(evidence, ensure_ascii=False).encode(),
                        "application/json",
                    ),
                },
            )
            assert buyer["status"] == "verified", buyer
            run = post(
                "/runs",
                {
                    "dataset_id": source["dataset_id"],
                    "modules": ["cutting", "assistant", "quality", "crm", "cards"],
                    "config_version": "independent-fault-no-applications",
                    "solver_config": {
                        "profile": "quick",
                        "seed": 101,
                        "workers": 1,
                        "time_limit_seconds": 5,
                        "minimum_free_remnants": 5,
                    },
                    "ai_profile": "local_limited",
                    "buyer_registry_version": buyer["version"],
                    "total_budget_seconds": 60,
                    "export_reserve_seconds": 5,
                },
            )
            rid = run["run_id"]
            report["run_id"] = rid
            deadline = time.monotonic() + 70
            while time.monotonic() < deadline:
                view = c.get(f"/api/v1/runs/{rid}").json()
                if len(view["jobs"]) == 5 and any(j["state"] == "failed" for j in view["jobs"]):
                    break
                time.sleep(0.1)
            report["initial_run"] = view
            exported = post(f"/runs/{rid}/export")
            report["initial_partial_export"] = exported
            old_hashes = {}
            for name, url in exported["files"].items():
                if name.endswith(".csv"):
                    response = c.get(url)
                    response.raise_for_status()
                    old_hashes[name] = hashlib.sha256(response.content).hexdigest()
            report["partial_export_honest"] = (
                exported["status"] == "partial" and "sale_cards.csv" not in exported["files"]
            )
            for restart in range(3):
                if restart:
                    process.terminate()
                    process.wait(timeout=15)
                    process = launch()
                    c.cookies.clear()
                    c.get("/api/v1/session").raise_for_status()
                for tick in range(5):
                    observed = c.get(f"/api/v1/runs/{rid}").json()
                    report["observations"].append(
                        {
                            "restart": restart,
                            "tick": tick,
                            "status": observed["status"],
                            "jobs": [
                                {"job_id": j["job_id"], "state": j["state"], "error_code": j["error_code"]}
                                for j in observed["jobs"]
                            ],
                        }
                    )
                    (args.out / "report.partial.json").write_bytes(
                        (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
                    )
                    time.sleep(0.6)
            report["old_downloads_unchanged"] = all(
                hashlib.sha256(c.get(exported["files"][name]).content).hexdigest() == digest
                for name, digest in old_hashes.items()
            )
            report["provider_calls"] = c.get("/api/v1/assistant/usage").json()["calls"]
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
        log.close()
        (args.out / "report.partial.json").write_bytes(
            (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
        )
    # Inspect the entire durable history after shutdown, not only latest_jobs projection.
    database = args.out / "data/glassflow.db"
    assert database.is_file(), database
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        counts = dict(
            db.execute(
                "SELECT kind, COUNT(*) FROM jobs WHERE run_id=? GROUP BY kind", (report["run_id"],)
            ).fetchall()
        )
    report["durable_job_counts"] = counts
    last = report["observations"][-1]
    report["failed_modules_terminal_not_forever_running"] = last["status"] in {"partial", "blocked"} and all(
        row["state"] in {"completed", "failed", "cancelled", "interrupted"} for row in last["jobs"]
    )
    report["status"] = (
        "PASS_BOUNDARY"
        if counts.get("cards") == 1
        and report["failed_modules_terminal_not_forever_running"]
        and report["partial_export_honest"]
        and report["old_downloads_unchanged"]
        and report["provider_calls"] == 0
        else "FAIL"
    )
    (args.out / "report.json").write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    print(
        json.dumps(
            {
                k: report[k]
                for k in [
                    "status",
                    "durable_job_counts",
                    "partial_export_honest",
                    "old_downloads_unchanged",
                    "provider_calls",
                ]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
