"""Measure actual local platform paths. Missing domain timings stay blocked."""

import hashlib
import json
import math
import os
import platform
import statistics
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from glassflow.main import create_app

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "1_ostatki/materials.csv",
    "1_ostatki/stock_open.csv",
    "1_ostatki/orders_open.csv",
    "2_assistant_crm/ksm_knowledge_base.json",
    "2_assistant_crm/applications_open.csv",
    "2_assistant_crm/questions_open.csv",
    "2_assistant_crm/dialogs_open.csv",
]


def summary(values):
    ordered = sorted(values)
    return {
        "count": len(values),
        "median_ms": statistics.median(values),
        "p95_ms": ordered[math.ceil(len(ordered) * 0.95) - 1],
        "min_ms": min(values),
        "max_ms": max(values),
        "samples_ms": values,
    }


def benchmark():
    files = [(Path(f).name, (ROOT / "inputs/PACK_for_teams" / f).read_bytes()) for f in FILES]
    report = {
        "measured_at": datetime.now(UTC).isoformat(),
        "os": platform.platform(),
        "cpu": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "python": platform.python_version(),
        "network": "not used",
        "inputs": {n: hashlib.sha256(c).hexdigest() for n, c in files},
        "scope": "TestClient HTTP + validation + SQLite staging; file selection/network excluded",
        "results": {},
    }
    if os.name == "nt":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong)
                for name in (
                    "total",
                    "available",
                    "page_total",
                    "page_available",
                    "virtual_total",
                    "virtual_available",
                    "extended",
                )
            ]

        memory = MemoryStatus()
        memory.length = ctypes.sizeof(memory)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory))
        report["physical_ram_gib"] = round(memory.total / 1024**3, 2)
    with tempfile.TemporaryDirectory(prefix="glassflow-benchmark-") as directory:
        with TestClient(create_app(Path(directory), testing=True)) as client:
            client.get("/api/v1/health")
            timings = []
            for _ in range(20):
                start = time.perf_counter()
                response = client.post("/api/v1/imports/preview", files=[("files", (n, c)) for n, c in files])
                elapsed = (time.perf_counter() - start) * 1000
                assert response.status_code == 200 and not response.json()["errors"]
                timings.append(elapsed)
            report["results"]["import_preview_20"] = summary(timings)
            imported = client.post(
                f"/api/v1/imports/{response.json()['import_id']}/commit",
                json={},
                headers={"Idempotency-Key": "benchmark"},
            ).json()
            for name, path, count in [
                ("manager_dashboard_100", "/api/v1/analytics/managers", 100),
                ("crm_ranking_100", "/api/v1/crm/rank", 100),
            ]:
                values = []
                for _ in range(count):
                    start = time.perf_counter()
                    params = {"dataset_id": imported["dataset_id"]}
                    response = (
                        client.get(path, params=params)
                        if "analytics" in path
                        else client.post(path, json=params)
                    )
                    assert response.status_code == 200
                    values.append((time.perf_counter() - start) * 1000)
                report["results"][name] = summary(values)
    for name in (
        "quote_100",
        "candidate_search",
        "first_plan",
        "extended_solver",
        "live_ai_30",
        "full_contest_run",
    ):
        report["results"][name] = {
            "status": "blocked",
            "reason": "C2/C3 services/live provider not integrated",
        }
    return report


if __name__ == "__main__":
    result = benchmark()
    destination = ROOT / "docs/release/platform-benchmark.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    for name, value in result["results"].items():
        print(name, {k: v for k, v in value.items() if k != "samples_ms"})
