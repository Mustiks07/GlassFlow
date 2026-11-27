"""Actual executable smoke; this machine is not claimed to be a clean Windows machine."""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def start(exe, directory):
    start = time.monotonic()
    process = subprocess.Popen(
        [str(exe), "--no-browser"],
        env={**os.environ, "GLASSFLOW_DATA_DIR": str(directory)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    deadline = start + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            out, err = process.communicate()
            raise RuntimeError(
                f"Frozen launch failed: {(out + err).decode('utf8', errors='replace')[-2000:]}"
            )
        info = directory / "launch.json"
        if info.exists():
            try:
                port = json.loads(info.read_text(encoding="utf8"))["port"]
                client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10)
                ready = client.get("/api/v1/ready")
                if ready.status_code == 200 and ready.json()["worker"]:
                    return process, client, (time.monotonic() - start) * 1000
                client.close()
            except (httpx.HTTPError, ValueError):
                pass
        time.sleep(0.1)
    process.terminate()
    process.communicate(timeout=5)
    raise RuntimeError("Frozen startup exceeded 45s")


def stop(process, client):
    token = client.get("/api/v1/session").json()["session_token"]
    response = client.post("/api/v1/system/shutdown", headers={"X-GlassFlow-Session": token})
    assert response.status_code == 200
    process.communicate(timeout=15)
    assert process.returncode == 0
    client.close()


def smoke(exe):
    native = subprocess.run(
        [str(exe), "--smoke-native-worker"], capture_output=True, text=True, encoding="utf8", timeout=90
    )
    assert native.returncode == 0, native.stderr
    result = json.loads(native.stdout.strip())
    assert result["frozen_worker"] is True and result["scipy_x"] == result["ortools_x"] == 2
    report = {
        "measured_at": datetime.now(UTC).isoformat(),
        "os": platform.platform(),
        "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
        "native_worker": result,
        "clean_windows": "not_run",
        "ui_flow": "not_run; C1 integration required",
    }
    from benchmark_platform import FILES

    with tempfile.TemporaryDirectory(prefix="glassflow-frozen-smoke-") as name:
        directory = Path(name)
        process, client, elapsed = start(exe, directory)
        try:
            report["first_start_ms"] = elapsed
            assert client.get("/").status_code == 200
            uploads = [
                ("files", (Path(f).name, (ROOT / "inputs/PACK_for_teams" / f).read_bytes())) for f in FILES
            ]
            preview = client.post("/api/v1/imports/preview", files=uploads)
            assert preview.status_code == 200 and not preview.json()["errors"], preview.text
            imported = client.post(
                f"/api/v1/imports/{preview.json()['import_id']}/commit",
                json={},
                headers={"Idempotency-Key": "smoke-import"},
            )
            assert imported.status_code == 200, imported.text
            dataset_id = imported.json()["dataset_id"]
            job = client.post(
                "/api/v1/runs",
                json={"dataset_id": dataset_id, "modules": ["crm"], "config_version": "frozen-smoke"},
                headers={"Idempotency-Key": "run"},
            )
            assert job.status_code == 202, job.text
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                progress = client.get(f"/api/v1/jobs/{job.json()['job_id']}").json()
                if progress["state"] in {"completed", "failed"}:
                    break
                time.sleep(0.1)
            assert progress["state"] == "completed", progress
            exported = client.post(
                f"/api/v1/runs/{job.json()['run_id']}/export", headers={"Idempotency-Key": "export"}
            ).json()
            picks = client.get(exported["files"]["picks.csv"]).content
            assert picks.startswith(b"app_id\r\n") and len(picks.splitlines()) == 26
            report["downloaded_picks_sha256"] = hashlib.sha256(picks).hexdigest()
            token = client.get("/api/v1/session").json()["session_token"]
            settings = client.patch(
                "/api/v1/settings",
                json={"model_id": "smoke-no-provider"},
                headers={"X-GlassFlow-Session": token},
            )
            assert settings.status_code == 200
            report["import_counts"] = imported.json()["row_counts"]
            report["crm_rows"] = len(progress["result"]["rows"])
        finally:
            stop(process, client)
        process, client, elapsed = start(exe, directory)
        try:
            report["restart_ms"] = elapsed
            assert client.get(f"/api/v1/datasets/{dataset_id}").status_code == 200
            assert client.get("/api/v1/settings").json()["model_id"] == "smoke-no-provider"
            report["persistence"] = "passed"
        finally:
            stop(process, client)
    report["status"] = "passed_on_build_machine"
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=ROOT / "dist/GlassFlow/GlassFlow.exe")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/release/frozen-smoke.json")
    args = parser.parse_args()
    result = smoke(args.exe.resolve())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
