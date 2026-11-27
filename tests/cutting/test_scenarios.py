"""Scenario tests on the open pack and on a NEW synthetic dataset (TEST data, permuted/renamed IDs).

T15 (extended target) is long: it runs only with GLASSFLOW_RUN_EXTENDED=1; its committed evidence is
tests/cutting/evidence/open_extended_evidence.json produced by the evidence CLI.
"""

import json
import os
import random
import statistics
import time
from decimal import Decimal
from pathlib import Path

import pytest

from glassflow.contracts.common import Dimensions
from glassflow.contracts.cutting import FindRequest, SolverConfig
from glassflow.modules.cutting.conversion import input_from_snapshot
from glassflow.modules.cutting.domain import PartSpec, RemnantSpec, Snapshot
from glassflow.modules.cutting.engine import CuttingEngine
from glassflow.modules.cutting.geometry import validate_plan
from glassflow.modules.cutting.service import CuttingService
from glassflow.modules.cutting.solver import SolverSettings, solve

from .conftest import InlineJobSubmitter, official_module, official_rows, register

API = "/api/v1"
EVIDENCE = Path(__file__).parent / "evidence"
TARGET_PERCENT = Decimal("58.9523237")


def permuted(snapshot: Snapshot, seed: int = 11) -> Snapshot:
    """Synthetic TEST dataset: new IDs, shuffled rows, same physical sizes."""
    rng = random.Random(seed)
    rids = list(snapshot.remnant_order)
    pids = list(snapshot.part_order)
    rng.shuffle(rids)
    rng.shuffle(pids)
    rmap = {rid: f"S{900 - i:03d}" for i, rid in enumerate(rids)}
    pmap = {pid: f"Q{5000 - i}" for i, pid in enumerate(pids)}
    remnants = {}
    for rid in rids:
        r = snapshot.remnants[rid]
        remnants[rmap[rid]] = RemnantSpec(rmap[rid], r.material_id, r.length_mm, r.width_mm, r.defect, r.age_days,
                                          "available", 0, r.location_raw, True)
    parts = {}
    for pid in pids:
        p = snapshot.parts[pid]
        parts[pmap[pid]] = PartSpec(pmap[pid], "X" + p.order_id, p.material_id, p.length_mm, p.width_mm, p.premium,
                                    p.product_type)
    return Snapshot("synthetic-permuted-test", snapshot.materials, remnants, parts)


def test_new_ids_and_row_permutation_give_valid_complete_plan(open_snapshot):
    synthetic = permuted(open_snapshot)
    outcome = solve(synthetic, SolverSettings(profile="quick", time_limit_seconds=10))
    rows = outcome.rows(synthetic)
    assert [r.part_id for r in rows] == synthetic.part_order  # exact input order of the new file
    assert validate_plan(synthetic, rows).valid
    official = official_module()
    stock, orders, mats = official_rows(synthetic)
    sol = [{"part_id": a.part_id, "remnant_id": a.remnant_id, "x_mm": "" if a.x_mm is None else str(a.x_mm),
            "y_mm": "" if a.y_mm is None else str(a.y_mm), "rot": "" if a.rot is None else str(a.rot)} for a in rows]
    _, _, ok, bad = official.check(stock, orders, sol, mats)
    assert bad == [] and len(ok) == len(outcome.assignments)
    original = solve(open_snapshot, SolverSettings(profile="quick", time_limit_seconds=10))
    # same physics, different names: quality must not depend on hard-coded IDs
    assert abs(outcome.covered_area - original.covered_area) / open_snapshot.total_part_area < 0.02
    assert not ({a.remnant_id for a in outcome.assignments.values()} & set(open_snapshot.remnants))


def test_open_pack_end_to_end_commit_candidate_quote_reserve_and_conflict(app_client, open_snapshot):
    app, client = app_client
    register(app, "open-ws", open_snapshot)
    app.state.job_submitter = InlineJobSubmitter(app)
    job = client.post(f"{API}/cutting/solve", json={"dataset_id": "open-ws", "config": {"profile": "quick"}}).json()
    plan_id, revision = job["result_ref"].split("@")
    plan = client.get(f"{API}/plans/{plan_id}", params={"dataset_id": "open-ws"}).json()
    assert plan["metrics"]["invalid"] == 0 and plan["metrics"]["missing"] == 0
    assert plan["metrics"]["total_parts"] == 298 and plan["metrics"]["free_original_remnants"] >= 5
    used = sorted({p["remnant_id"] for p in plan["placements"] if p["remnant_id"] != "NEW"})
    versions = {rid: 0 for rid in used}
    committed = client.post(f"{API}/plans/{plan_id}/commit", json={"dataset_id": "open-ws", "plan_revision": int(revision),
                                                                    "expected_remnant_versions": versions})
    assert committed.status_code == 200 and len(committed.json()["reservations"]) == len(used)
    # no-replan mode: a 450x370 clear-6 request goes only to fully free original pieces
    found = client.post(f"{API}/cutting/candidates", json={"dataset_id": "open-ws", "material_id": "clear-6",
                                                           "dimensions": {"length_mm": 450, "width_mm": 370}}).json()
    assert found["candidates"], found
    best = found["candidates"][0]
    assert best["remnant_id"] not in used and (best["x_mm"], best["y_mm"]) == (5, 5)
    # T23: the piece changes while the AI answer is being written -> confirmation with the old version fails
    client.patch(f"{API}/remnants/{best['remnant_id']}", json={"dataset_id": "open-ws",
                                                               "expected_version": best["remnant_version"],
                                                               "location_raw": "Стеллаж A, ячейка 99"})
    stale = client.post(f"{API}/remnants/{best['remnant_id']}/reserve", json={
        "dataset_id": "open-ws", "expected_version": best["remnant_version"], "owner_context": "quote:Q1@1",
        "material_id": "clear-6", "dimensions": {"length_mm": 450, "width_mm": 370}, "x_mm": 5, "y_mm": 5,
        "rot": best["rot"]})
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    fresh = client.get(f"{API}/remnants/{best['remnant_id']}", params={"dataset_id": "open-ws"}).json()
    reserved = client.post(f"{API}/remnants/{best['remnant_id']}/reserve", headers={"Idempotency-Key": "q1"}, json={
        "dataset_id": "open-ws", "expected_version": fresh["version"], "owner_context": "quote:Q1@1",
        "material_id": "clear-6", "dimensions": {"length_mm": 450, "width_mm": 370}, "x_mm": 5, "y_mm": 5,
        "rot": best["rot"]})
    assert reserved.status_code == 200 and reserved.json()["remnant"]["status"] == "reserved"
    again = client.post(f"{API}/remnants/{best['remnant_id']}/reserve", headers={"Idempotency-Key": "q1"}, json={
        "dataset_id": "open-ws", "expected_version": fresh["version"], "owner_context": "quote:Q1@1",
        "material_id": "clear-6", "dimensions": {"length_mm": 450, "width_mm": 370}, "x_mm": 5, "y_mm": 5,
        "rot": best["rot"]})
    assert again.json() == reserved.json()
    # it no longer appears as free and no plan can take it without an explicit release
    after = client.post(f"{API}/cutting/candidates", json={"dataset_id": "open-ws", "material_id": "clear-6",
                                                           "dimensions": {"length_mm": 450, "width_mm": 370}}).json()
    assert best["remnant_id"] not in {c["remnant_id"] for c in after["candidates"]}
    occupied = client.post(f"{API}/remnants/{used[0]}/reserve", json={
        "dataset_id": "open-ws", "expected_version": 1, "owner_context": "quote:Q2@1", "material_id": "clear-6",
        "dimensions": {"length_mm": 100, "width_mm": 100}})
    assert occupied.status_code == 409


def test_candidate_search_p95_under_one_second(app_client, open_snapshot):
    """TZ 27: single new part search p95 <= 1 s with 200 remnants and fixed existing jobs (measured)."""
    app, client = app_client
    register(app, "perf", open_snapshot)
    with app.state.session_factory() as session:
        service = CuttingService(session)
        rng = random.Random(3)
        materials = sorted(open_snapshot.materials)
        durations = []
        for _ in range(200):
            request = FindRequest(dataset_id="perf", material_id=rng.choice(materials),
                                  dimensions=Dimensions(length_mm=rng.randint(200, 1500), width_mm=rng.randint(200, 900)),
                                  premium=rng.random() < 0.3)
            started = time.perf_counter()
            service.find_candidates(request)
            durations.append(time.perf_counter() - started)
    durations.sort()
    p95 = durations[int(0.95 * len(durations)) - 1]
    EVIDENCE.mkdir(exist_ok=True)
    (EVIDENCE / "candidate_search_timing.json").write_text(json.dumps({
        "runs": len(durations), "median_ms": round(statistics.median(durations) * 1000, 2),
        "p95_ms": round(p95 * 1000, 2), "max_ms": round(durations[-1] * 1000, 2), "remnants": 200,
        "note": "service-level timing incl. SQLite reads, developer laptop; not the reference machine"}, indent=2),
        encoding="utf-8")
    assert p95 < 1.0


@pytest.mark.skipif(os.environ.get("GLASSFLOW_RUN_EXTENDED") != "1", reason="600 s profile; set GLASSFLOW_RUN_EXTENDED=1")
def test_t15_extended_profile_reaches_research_reference(open_snapshot):
    plan = CuttingEngine().solve(input_from_snapshot(open_snapshot, config=SolverConfig(
        profile="extended", time_limit_seconds=600, workers=max(1, (os.cpu_count() or 2) - 1))), None)
    assert plan.metrics.invalid == 0 and plan.metrics.missing == 0
    assert Decimal(plan.metrics.coverage_percent) >= TARGET_PERCENT - Decimal("0.000001")


@pytest.mark.parametrize("evidence_path", sorted(EVIDENCE.glob("open_extended*_evidence.json")),
                         ids=lambda p: p.name)
def test_t15_committed_evidence_is_consistent(evidence_path):
    """Every committed evidence must show the official validator run on its own committed solution file."""
    import hashlib

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["validator"]["exit_code"] == 0 and evidence["validator"]["invalid"] == "0"
    assert evidence["metrics"]["missing"] == 0 and evidence["metrics"]["invalid"] == 0
    assert Decimal(evidence["metrics"]["coverage_percent"]) >= TARGET_PERCENT - Decimal("0.000001")
    solution = Path(evidence["solution"]["path"])
    solution = solution if solution.is_absolute() else Path(__file__).resolve().parents[2] / solution
    assert hashlib.sha256(solution.read_bytes()).hexdigest() == evidence["solution"]["sha256"]
