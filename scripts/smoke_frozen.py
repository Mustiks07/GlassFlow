"""Actual executable smoke; this machine is not claimed to be a clean Windows machine."""

import argparse
import csv
import hashlib
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
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
    diagnostics = exe.with_name("GlassFlowDiagnostics.exe")
    assert diagnostics.is_file(), "Missing diagnostics executable in onedir bundle"

    def subsystem(path):
        data = path.read_bytes()
        pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
        return struct.unpack_from("<H", data, pe_offset + 24 + 68)[0]

    assert subsystem(exe) == 2 and subsystem(diagnostics) == 3
    native = subprocess.run(
        [str(diagnostics), "--smoke-native-worker"],
        capture_output=True,
        text=True,
        encoding="utf8",
        timeout=90,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    assert native.returncode == 0, native.stderr
    result = json.loads(native.stdout.strip())
    assert result["frozen_worker"] is True and result["scipy_x"] == result["ortools_x"] == 2
    assert result["worker_executable"] == "GlassFlow.exe"
    report = {
        "measured_at": datetime.now(UTC).isoformat(),
        "os": platform.platform(),
        "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
        "native_worker": result,
        "pe_subsystem": {"main": subsystem(exe), "diagnostics": subsystem(diagnostics)},
        "clean_windows": "not_run",
        "ui_flow": "not_run; C1 integration required",
    }
    stamp = exe.parent / "_internal/glassflow/build-info.json"
    if stamp.is_file():
        info = json.loads(stamp.read_text(encoding="utf8"))
        report["build_commit"], report["runtime_source_digest"] = info["commit"], info["source_digest"]
    with tempfile.TemporaryDirectory(prefix="glassflow-frozen-validator-") as name:
        directory = Path(name)
        for kind, filename in {
            "stock": "stock_open.csv",
            "orders": "orders_open.csv",
            "materials": "materials.csv",
        }.items():
            shutil.copyfile(
                ROOT / "inputs/PACK_for_teams/1_ostatki" / filename, directory / f"input-{kind}.csv"
            )
        with (directory / "input-orders.csv").open(encoding="utf8", newline="") as handle:
            parts = list(csv.DictReader(handle))
        with (directory / "solution.csv").open("w", encoding="utf8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["part_id", "remnant_id", "x_mm", "y_mm", "rot"])
            writer.writeheader()
            writer.writerows(
                {"part_id": p["part_id"], "remnant_id": "NEW", "x_mm": "", "y_mm": "", "rot": ""}
                for p in parts
            )
        checked = subprocess.run(
            [str(diagnostics), "--official-validator", str(directory)],
            capture_output=True,
            text=True,
            encoding="utf8",
            timeout=30,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        assert checked.returncode == 0 and "invalid=0" in checked.stdout, checked.stderr
        report["official_validator_cli"] = {
            "fixture": "synthetic all-NEW; format only, not solver acceptance",
            "exit_code": checked.returncode,
            "stdout": checked.stdout,
            "stderr": checked.stderr,
        }
    from benchmark_platform import FILES

    with tempfile.TemporaryDirectory(prefix="glassflow-frozen-smoke-") as name:
        directory = Path(name)
        process, client, elapsed = start(exe, directory)
        try:
            report["first_start_ms"] = elapsed
            assert client.get("/").status_code == 200
            second = subprocess.run(
                [str(exe), "--no-browser"],
                env={**os.environ, "GLASSFLOW_DATA_DIR": str(directory)},
                capture_output=True,
                text=True,
                encoding="utf8",
                timeout=15,
            )
            assert second.returncode == 0
            assert json.loads((directory / "launch.json").read_text(encoding="utf8"))["pid"] == process.pid
            report["singleton"] = "passed"
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
            (directory / "downloaded-picks.csv").write_bytes(picks)
            evaluated = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    str(ROOT / "inputs/PACK_for_teams/2_assistant_crm/selfcheck.py"),
                    "crm",
                    str(directory / "downloaded-picks.csv"),
                    str(ROOT / "inputs/PACK_for_teams/2_assistant_crm/applications_open.csv"),
                ],
                capture_output=True,
                text=True,
                encoding="utf8",
                timeout=30,
            )
            assert evaluated.returncode == 0 and "10.0 из 10" in evaluated.stdout, evaluated.stderr
            report["official_crm_open_evaluation"] = {
                "exit_code": evaluated.returncode,
                "stdout": evaluated.stdout,
                "stderr": evaluated.stderr,
                "closed_accuracy": None,
            }
            token = client.get("/api/v1/session").json()["session_token"]
            settings = client.patch(
                "/api/v1/settings",
                json={"model_id": "smoke-no-provider"},
                headers={"X-GlassFlow-Session": token},
            )
            assert settings.status_code == 200
            report["import_counts"] = imported.json()["row_counts"]
            report["crm_rows"] = len(progress["result"]["rows"])
            backup = client.post("/api/v1/system/backup", headers={"X-GlassFlow-Session": token})
            assert backup.status_code == 200
            backup_id = backup.json()["backup_id"]
        finally:
            stop(process, client)
        process, client, elapsed = start(exe, directory)
        try:
            report["restart_ms"] = elapsed
            assert client.get(f"/api/v1/datasets/{dataset_id}").status_code == 200
            assert client.get("/api/v1/settings").json()["model_id"] == "smoke-no-provider"
            report["persistence"] = "passed"
            baseline_count = len(client.get("/api/v1/datasets").json())
            added = client.post(
                f"/api/v1/datasets/{dataset_id}/working-copy",
                json={},
                headers={"Idempotency-Key": "restore-test-copy"},
            )
            assert added.status_code == 200
            assert len(client.get("/api/v1/datasets").json()) == baseline_count + 1
            token = client.get("/api/v1/session").json()["session_token"]
            restore = client.post(
                "/api/v1/system/restore",
                json={"backup_id": backup_id, "confirm_replace": True},
                headers={"X-GlassFlow-Session": token},
            )
            assert restore.status_code == 200 and restore.json()["status"] == "pending_restart"
        finally:
            stop(process, client)
        process, client, elapsed = start(exe, directory)
        try:
            assert len(client.get("/api/v1/datasets").json()) == baseline_count
            assert client.get("/api/v1/settings").json()["model_id"] == "smoke-no-provider"
            report["backup_restore"] = "passed"
            report["restore_restart_ms"] = elapsed
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
    # Hosted Windows runners may expose a cp1252 console; the UTF-8 report above
    # preserves the validator text while ASCII escaping keeps CI output portable.
    print(json.dumps(result, ensure_ascii=True, indent=2))
