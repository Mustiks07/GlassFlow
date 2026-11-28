"""Synthetic HTTP/service comparison for N03, not an acceptance E2E or demand forecast."""

from __future__ import annotations

import json
import platform
import tempfile
import time
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from glassflow.main import create_app
from glassflow.modules.cutting.domain import Assignment, MaterialSpec, PartSpec, RemnantSpec, Snapshot
from glassflow.modules.cutting.geometry import validate_plan
from glassflow.modules.cutting.service import CuttingService
from glassflow.modules.cutting.uow import write_transaction


def run():
    rows = []
    with tempfile.TemporaryDirectory(prefix="glassflow-scarcity-") as directory:
        app = create_app(Path(directory), testing=True)
        with TestClient(app) as client:
            client.get("/api/v1/health").raise_for_status()
            for repeat in range(6):
                for case in (
                    "quantity1",
                    "quantity2",
                    "joint_impossible",
                    "reserved",
                    "not_scarce",
                    "tiny_budget",
                ):
                    dataset = f"n03-{case}-changed-{repeat * 29 + 3}"
                    narrow, square = f"{dataset}-long", f"{dataset}-other"
                    materials = {"glass": MaterialSpec("glass", False, Decimal("4500"))}
                    pieces = {
                        square: RemnantSpec(
                            square,
                            "glass",
                            300 if case == "not_scarce" else 160,
                            250 if case == "not_scarce" else 160,
                            False,
                            0,
                            "reserved" if case == "reserved" else "available",
                            2,
                            "R2",
                            True,
                        ),
                        narrow: RemnantSpec(narrow, "glass", 210, 110, False, 10, "available", 1, "R1", True),
                    }
                    parts = {
                        f"{dataset}-part-{i * 13 + 7}": PartSpec(
                            f"{dataset}-part-{i * 13 + 7}", f"{dataset}-order", "glass", 200, 100, False
                        )
                        for i in range(2 if case == "joint_impossible" else 1)
                    }
                    snapshot = Snapshot(dataset, materials, pieces, parts)
                    with write_transaction(app.state.session_factory) as session:
                        CuttingService(session).register_dataset(dataset, "workspace", snapshot)
                    body = dict(
                        dataset_id=dataset,
                        material_id="glass",
                        dimensions=dict(length_mm=80, width_mm=40),
                        quantity=2 if case == "quantity2" else 1,
                        budget_ms=1 if case == "tiny_budget" else 300,
                    )
                    started = time.perf_counter()
                    normal = client.post(
                        "/api/v1/cutting/candidates", json={k: v for k, v in body.items() if k != "budget_ms"}
                    )
                    normal.raise_for_status()
                    normal_ms = (time.perf_counter() - started) * 1000
                    started = time.perf_counter()
                    response = client.post("/api/v1/cutting/scarcity", json=body)
                    response.raise_for_status()
                    elapsed = (time.perf_counter() - started) * 1000
                    result = response.json()
                    unchanged = normal.json() == result["baseline"]
                    valid = True
                    for explanation in result["explanations"]:
                        joint_parts = dict(parts)
                        for pid in explanation["request_part_ids"]:
                            joint_parts[pid] = PartSpec(pid, "request", "glass", 80, 40, False)
                        witness = [
                            Assignment(p["part_id"], p["remnant_id"], p["x_mm"], p["y_mm"], p["rot"])
                            for p in explanation["joint_witness"]
                        ]
                        valid = (
                            valid
                            and validate_plan(
                                Snapshot(dataset, materials, pieces, joint_parts), witness
                            ).valid
                        )
                    expected = (
                        result["status"] in {"proved", "limited"}
                        if case in {"quantity1", "quantity2", "tiny_budget"}
                        else result["status"] == "no_proof"
                    )
                    rows.append(
                        dict(
                            case=case,
                            repeat=repeat,
                            dataset_id=dataset,
                            cold=not rows,
                            http_ms=elapsed,
                            baseline_http_ms=normal_ms,
                            status=result["status"],
                            baseline_unchanged=unchanged,
                            independently_valid=valid,
                            expected=expected,
                            response=result,
                        )
                    )
    warm = sorted(r["http_ms"] for r in rows if not r["cold"])
    report = dict(
        kind="synthetic HTTP/service experiment, not real production E2E",
        platform=platform.platform(),
        python=platform.python_version(),
        budget_ms=300,
        tiny_budget_ms=1,
        samples=rows,
        p95_warm_http_ms=warm[int(len(warm) * 0.95 + 0.999) - 1],
        all_checks=all(r["baseline_unchanged"] and r["independently_valid"] and r["expected"] for r in rows),
        ordering_decision="unchanged baseline; optional independently checked joint advice only",
        cold_note="Cold native import can exhaust budget; limited keeps ordinary candidates and makes no reason claim.",
    )
    (Path(__file__).parent / "scarcity-comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "samples"}, ensure_ascii=False, indent=2))
    if not report["all_checks"] or report["p95_warm_http_ms"] >= 1000:
        raise SystemExit(1)


if __name__ == "__main__":
    run()
