"""HTTP + real SQLite integration: inventory, plans, editor, atomic commit, idempotency, restart.

Covers T16, T18, T19, T20, T22 (server side) and the support parts of T04/T05/T23/T48.
The only test double is ``InlineJobSubmitter`` standing in for the platform queue.
"""

import threading

from fastapi.testclient import TestClient

from glassflow.main import create_app

from .conftest import InlineJobSubmitter, make_snapshot, register

API = "/api/v1"


def small_snapshot():
    return make_snapshot(
        [("R1", "clear-4", 600, 400, False, 300), ("R2", "clear-4", 600, 400, False, 100),
         ("R3", "clear-4", 300, 300, True, 50), ("R4", "mirror-4", 500, 500, False, 20),
         ("T1", "temp-6", 600, 400, False, 10), ("R5", "clear-4", 250, 250, False, 5),
         ("R6", "clear-4", 260, 260, False, 5), ("R7", "clear-4", 270, 270, False, 5)],
        [("P1", "O1", "clear-4", 400, 300, False), ("P2", "O1", "clear-4", 150, 100, False),
         ("P3", "O2", "clear-4", 280, 280, True), ("P4", "O3", "mirror-4", 480, 480, False),
         ("P5", "O4", "temp-6", 599, 401, False), ("P6", "O5", "clear-4", 2000, 100, False)])


def solve(app, client, dataset="ws", **body):
    app.state.job_submitter = InlineJobSubmitter(app)
    payload = {"dataset_id": dataset, "config": {"profile": "standard", "time_limit_seconds": 10,
                                                 "minimum_free_remnants": 0}} | body
    job = client.post(f"{API}/cutting/solve", json=payload)
    assert job.status_code == 202, job.text
    plan_id, revision = job.json()["result_ref"].split("@")
    return client.get(f"{API}/plans/{plan_id}", params={"dataset_id": dataset}).json()


def versions(client, dataset, plan):
    used = {p["remnant_id"] for p in plan["placements"] if p["remnant_id"] != "NEW"}
    return {rid: client.get(f"{API}/remnants/{rid}", params={"dataset_id": dataset}).json()["version"] for rid in used}


def commit(client, dataset, plan, key=None, owner="test"):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post(f"{API}/plans/{plan['plan_id']}/commit", headers=headers, json={
        "dataset_id": dataset, "plan_revision": plan["revision"],
        "expected_remnant_versions": versions(client, dataset, plan), "owner_context": owner})


def test_solve_without_platform_is_honest_503(app_client):
    app, client = app_client
    register(app, "ws", small_snapshot())
    response = client.post(f"{API}/cutting/solve", json={"dataset_id": "ws"})
    assert response.status_code == 503 and response.json()["code"] == "JOB_PLATFORM_UNAVAILABLE"


def test_list_filter_paginate_and_dataset_isolation(app_client):
    app, client = app_client
    register(app, "ws", small_snapshot())
    other = make_snapshot([("R1", "mirror-4", 999, 999, False)], [("P1", "OX", "mirror-4", 10, 10, False)])
    register(app, "other", other, mode="source")  # same external IDs, different dataset (T04)
    page = client.get(f"{API}/datasets/ws/remnants", params={"material_id": "clear-4", "limit": 2, "sort": "area",
                                                              "descending": True}).json()
    assert page["total"] == 6 and [r["remnant_id"] for r in page["items"]] == ["R1", "R2"]
    assert page["items"][0]["rack"] == "T" and page["items"][0]["cell"] == "R1"
    r1_other = client.get(f"{API}/remnants/R1", params={"dataset_id": "other"}).json()
    assert r1_other["material_id"] == "mirror-4" and r1_other["internal_id"] != client.get(
        f"{API}/remnants/R1", params={"dataset_id": "ws"}).json()["internal_id"]
    legacy = client.get(f"{API}/remnants", params={"dataset_id": "ws", "limit": 3})
    assert len(legacy.json()) == 3 and legacy.headers["X-Total-Count"] == "8"
    assert client.get(f"{API}/remnants/R9", params={"dataset_id": "ws"}).status_code == 404


def test_t20_add_restart_reserve_consume_history(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        register(app, "ws", small_snapshot())
        added = client.post(f"{API}/remnants", json={"dataset_id": "ws", "material_id": "clear-4",
                                                     "dimensions": {"length_mm": 700, "width_mm": 500},
                                                     "defect": False, "location_raw": "Стеллаж Z, ячейка 9"})
        assert added.status_code == 200, added.text
        new = added.json()
        assert new["remnant_id"].startswith("W") and new["age_days"] is None and not new["original"]
        assert new["rack"] == "Z" and new["cell"] == "9"
        bad = client.post(f"{API}/remnants", json={"dataset_id": "ws", "material_id": "nope", "defect": False,
                                                   "dimensions": {"length_mm": 7, "width_mm": 5}, "location_raw": "x"})
        assert bad.status_code == 422 and bad.json()["code"] == "UNKNOWN_MATERIAL"
    # restart: a new app instance on the same data directory
    app = create_app(tmp_path)
    with TestClient(app) as client:
        stored = client.get(f"{API}/remnants/{new['remnant_id']}", params={"dataset_id": "ws"}).json()
        assert stored["location_raw"] == "Стеллаж Z, ячейка 9" and stored["status"] == "available"
        plan = solve(app, client, locks=[{"part_id": "P1", "remnant_id": new["remnant_id"], "lock_kind": "assignment"}])
        on_new = [p for p in plan["placements"] if p["remnant_id"] == new["remnant_id"]]
        assert on_new and on_new[0]["part_id"] == "P1" and on_new[0]["lock_kind"] == "assignment"
        result = commit(client, "ws", plan)
        assert result.status_code == 200, result.text
        reservation = next(r for r in result.json()["reservations"] if r["remnant_id"] == new["remnant_id"])
        piece = client.get(f"{API}/remnants/{new['remnant_id']}", params={"dataset_id": "ws"}).json()
        assert piece["status"] == "reserved" and piece["active_reservation_id"] == reservation["reservation_id"]
        consumed = client.post(f"{API}/remnants/{new['remnant_id']}/consume", json={
            "dataset_id": "ws", "expected_version": piece["version"], "reservation_id": reservation["reservation_id"],
            "reason": "раскроено"})
        assert consumed.status_code == 200 and consumed.json()["remnant"]["status"] == "consumed"
        again = client.post(f"{API}/remnants/{new['remnant_id']}/release", json={
            "dataset_id": "ws", "expected_version": consumed.json()["remnant"]["version"]})
        assert again.status_code == 409 and again.json()["code"] == "REMNANT_CONSUMED"
        found = client.post(f"{API}/cutting/candidates", json={"dataset_id": "ws", "material_id": "clear-4",
                                                               "dimensions": {"length_mm": 650, "width_mm": 450}})
        assert all(c["remnant_id"] != new["remnant_id"] for c in found.json()["candidates"])
        history = client.get(f"{API}/cutting/events", params={"dataset_id": "ws", "object_id": new["remnant_id"]}).json()
        assert [e["action"] for e in history] == ["remnant.added", "remnant.reserved", "remnant.consumed"]
        children = client.post(f"{API}/remnants/{new['remnant_id']}/children", json={
            "dataset_id": "ws", "expected_version": consumed.json()["remnant"]["version"],
            "children": [{"dimensions": {"length_mm": 280, "width_mm": 180}, "location_raw": "Стеллаж Z, ячейка 10"}]})
        assert children.status_code == 200
        child = children.json()["children"][0]
        assert child["origin"] == "child" and not child["original"] and child["parent_remnant_id"] == new["remnant_id"]


def test_immutable_source_dataset_rejects_working_mutations(app_client):
    app, client = app_client
    register(app, "src", small_snapshot(), mode="source")
    response = client.post(f"{API}/remnants", json={"dataset_id": "src", "material_id": "clear-4", "defect": False,
                                                    "dimensions": {"length_mm": 700, "width_mm": 500},
                                                    "location_raw": "A"})
    assert response.status_code == 409 and response.json()["code"] == "IMMUTABLE_DATASET"
    withdraw = client.post(f"{API}/remnants/R1/withdraw", json={"dataset_id": "src", "expected_version": 0,
                                                                "reason": "x"})
    assert withdraw.status_code == 409


def test_t18_two_concurrent_commits_one_success_one_409(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        register(app, "ws", small_snapshot())
        plan_a = solve(app, client)
        plan_b = solve(app, client)
        shared = set(versions(client, "ws", plan_a)) & set(versions(client, "ws", plan_b))
        assert shared
        barrier = threading.Barrier(2)
        results = {}

        def run(name, plan):
            body = {"dataset_id": "ws", "plan_revision": plan["revision"],
                    "expected_remnant_versions": versions(client, "ws", plan), "owner_context": name}
            barrier.wait()
            results[name] = client.post(f"{API}/plans/{plan['plan_id']}/commit", json=body)

        threads = [threading.Thread(target=run, args=("a", plan_a)), threading.Thread(target=run, args=("b", plan_b))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        codes = sorted(r.status_code for r in results.values())
        assert codes == [200, 409], [r.text for r in results.values()]
        loser = next(r for r in results.values() if r.status_code == 409).json()
        assert loser["code"] in {"VERSION_CONFLICT", "CONCURRENT_UPDATE", "DOUBLE_RESERVATION", "CONCURRENT_COMMIT"}
        with app.state.session_factory() as session:
            from sqlalchemy import func, select

            from glassflow.modules.cutting.models import CutPlanRow, CutReservation

            active = session.scalars(select(CutReservation.remnant_row_id).where(CutReservation.status == "active")).all()
            assert len(active) == len(set(active))
            assert session.scalar(select(func.count()).select_from(CutPlanRow).where(
                CutPlanRow.status == "committed")) == 1


def test_t19_idempotent_commit_same_key_same_result_other_body_conflict(app_client):
    app, client = app_client
    register(app, "ws", small_snapshot())
    plan = solve(app, client)
    body = {"dataset_id": "ws", "plan_revision": plan["revision"],
            "expected_remnant_versions": versions(client, "ws", plan), "owner_context": "m1"}
    first = client.post(f"{API}/plans/{plan['plan_id']}/commit", headers={"Idempotency-Key": "k-1"}, json=body)
    assert first.status_code == 200
    events_before = len(client.get(f"{API}/cutting/events", params={"dataset_id": "ws"}).json())
    second = client.post(f"{API}/plans/{plan['plan_id']}/commit", headers={"Idempotency-Key": "k-1"}, json=body)
    assert second.status_code == 200 and second.json() == first.json()
    assert len(client.get(f"{API}/cutting/events", params={"dataset_id": "ws"}).json()) == events_before
    other = client.post(f"{API}/plans/{plan['plan_id']}/commit", headers={"Idempotency-Key": "k-1"},
                        json=body | {"owner_context": "m2"})
    assert other.status_code == 409 and other.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    no_key_repeat = client.post(f"{API}/plans/{plan['plan_id']}/commit", json=body)
    assert no_key_repeat.status_code == 409  # without a key a repeat cannot double-reserve


def test_t22_invalid_drag_is_rejected_by_server_and_draft_can_be_fixed(app_client):
    app, client = app_client
    register(app, "ws", small_snapshot())
    plan = solve(app, client)
    assert commit(client, "ws", plan).status_code == 200
    p2 = next(p for p in plan["placements"] if p["part_id"] == "P2")
    assert p2["remnant_id"] != "NEW"
    drag = client.post(f"{API}/plans/{plan['plan_id']}/draft", json={
        "dataset_id": "ws", "base_revision": plan["revision"],
        "edits": [{"part_id": "P2", "action": "move", "remnant_id": p2["remnant_id"], "x_mm": 2, "y_mm": 5, "rot": 0}]})
    assert drag.status_code == 200
    bad = drag.json()
    assert bad["plan"]["status"] == "invalid" and not bad["validation"]["valid"]
    issue = next(i for i in bad["validation"]["issues"] if i["part_id"] == "P2")
    assert issue["code"] == "OUT_OF_BOUNDS" and issue["coordinates"]["x_mm"] == 2
    refused = client.post(f"{API}/plans/{plan['plan_id']}/commit", json={
        "dataset_id": "ws", "plan_revision": bad["plan"]["revision"], "expected_remnant_versions": {}})
    assert refused.status_code == 409 and refused.json()["code"] == "PLAN_NOT_COMMITTABLE"
    blocked = client.get(f"{API}/plans/{plan['plan_id']}/export", params={"dataset_id": "ws",
                                                                          "revision": bad["plan"]["revision"]})
    assert blocked.status_code == 409
    active = client.get(f"{API}/plans/active", params={"dataset_id": "ws"}).json()
    assert active["revision"] == plan["revision"] and active["status"] == "committed"
    # fix: move it back to a valid position as a new revision; the committed one stays untouched
    fixed = client.post(f"{API}/plans/{plan['plan_id']}/draft", json={
        "dataset_id": "ws", "base_revision": bad["plan"]["revision"],
        "edits": [{"part_id": "P2", "action": "move", "remnant_id": p2["remnant_id"], "x_mm": p2["x_mm"],
                   "y_mm": p2["y_mm"], "rot": p2["rot"]}]}).json()
    assert fixed["plan"]["status"] == "draft" and fixed["validation"]["valid"]
    assert client.post(f"{API}/plans/{plan['plan_id']}/validate",
                       params={"dataset_id": "ws", "revision": fixed["plan"]["revision"]}).json()["valid"]


def test_t16_locks_exclusion_impact_and_compare_keep_active_plan(app_client):
    app, client = app_client
    register(app, "ws", small_snapshot())
    plan = solve(app, client)
    assert commit(client, "ws", plan).status_code == 200
    p1 = next(p for p in plan["placements"] if p["part_id"] == "P1")
    impact = client.post(f"{API}/cutting/impact", json={"dataset_id": "ws", "remnant_id": p1["remnant_id"],
                                                        "change": "exclude"}).json()
    assert "P1" in impact["affected_part_ids"] and impact["delta_covered_area_mm2"] <= -400 * 300
    assert impact["affected_reservation_ids"] and impact["requires_commit"]
    # replan excluding the piece, with P2 locked in place
    p2 = next(p for p in plan["placements"] if p["part_id"] == "P2")
    lock = {"part_id": "P2", "remnant_id": p2["remnant_id"], "x_mm": p2["x_mm"], "y_mm": p2["y_mm"], "rot": p2["rot"],
            "lock_kind": "placement"}
    excluded = p1["remnant_id"] if p1["remnant_id"] != p2["remnant_id"] else None
    candidate = solve(app, client, locks=[lock], excluded_remnant_ids=[excluded] if excluded else [])
    assert all(p["remnant_id"] != excluded for p in candidate["placements"])
    cp2 = next(p for p in candidate["placements"] if p["part_id"] == "P2")
    assert (cp2["remnant_id"], cp2["x_mm"], cp2["y_mm"], cp2["rot"]) == (lock["remnant_id"], lock["x_mm"], lock["y_mm"],
                                                                         lock["rot"])
    diff = client.post(f"{API}/plans/compare", json={
        "dataset_id": "ws", "base": {"plan_id": plan["plan_id"], "revision": plan["revision"]},
        "candidate": {"plan_id": candidate["plan_id"], "revision": candidate["revision"]}}).json()
    assert diff["delta_covered_area_mm2"] == candidate["metrics"]["covered_area_mm2"] - plan["metrics"]["covered_area_mm2"]
    assert any(c["part_id"] == "P1" for c in diff["changes"]) and diff["affected_reserved_remnant_ids"]
    active = client.get(f"{API}/plans/active", params={"dataset_id": "ws"}).json()
    assert (active["plan_id"], active["revision"]) == (plan["plan_id"], plan["revision"])  # unchanged until commit
    switched = commit(client, "ws", candidate)
    assert switched.status_code == 200 and switched.json()["superseded_plan"] == f"{plan['plan_id']}@{plan['revision']}"
    if excluded:
        piece = client.get(f"{API}/remnants/{excluded}", params={"dataset_id": "ws"}).json()
        assert piece["status"] == "available"  # released when the old plan was superseded


def test_measurement_and_withdraw_flow_with_versions(app_client):
    app, client = app_client
    register(app, "ws", small_snapshot())
    stale = client.patch(f"{API}/remnants/R5/measurement", json={
        "dataset_id": "ws", "expected_version": 3, "dimensions": {"length_mm": 240, "width_mm": 240}})
    assert stale.status_code == 409 and stale.json()["conflict_objects"] == ["R5"]
    wrong_prev = client.patch(f"{API}/remnants/R5/measurement", json={
        "dataset_id": "ws", "expected_version": 0, "dimensions": {"length_mm": 240, "width_mm": 240},
        "previous_dimensions": {"length_mm": 251, "width_mm": 250}})
    assert wrong_prev.json()["code"] == "PREVIOUS_MEASUREMENT_MISMATCH"
    ok = client.patch(f"{API}/remnants/R5/measurement", json={
        "dataset_id": "ws", "expected_version": 0, "dimensions": {"length_mm": 240, "width_mm": 240},
        "previous_dimensions": {"length_mm": 250, "width_mm": 250}})
    assert ok.status_code == 200 and ok.json()["remnant_version"] == 1
    w = client.post(f"{API}/remnants/R5/withdraw", json={"dataset_id": "ws", "expected_version": 1, "reason": "скол"})
    assert w.json()["remnant"]["status"] == "withdrawn"
    restored = client.post(f"{API}/remnants/R5/restore", json={"dataset_id": "ws", "expected_version": 2})
    assert restored.json()["remnant"]["status"] == "available"
    upd = client.patch(f"{API}/remnants/R5", json={"dataset_id": "ws", "expected_version": 3,
                                                   "location_raw": "Стеллаж B, ячейка 4", "age_days": 12})
    assert upd.json()["rack"] == "B" and upd.json()["age_days"] == 12


def test_fast_candidates_single_quantity_and_reasons(app_client):
    app, client = app_client
    register(app, "ws", small_snapshot())
    one = client.post(f"{API}/cutting/candidates", json={"dataset_id": "ws", "material_id": "clear-4",
                                                         "dimensions": {"length_mm": 240, "width_mm": 240}}).json()
    assert one["covered_quantity"] == 1 and one["candidates"][0]["remnant_id"] == "R5"  # tightest fit first
    assert (one["candidates"][0]["x_mm"], one["candidates"][0]["y_mm"]) == (5, 5)
    many = client.post(f"{API}/cutting/candidates", json={"dataset_id": "ws", "material_id": "clear-4", "quantity": 4,
                                                          "dimensions": {"length_mm": 280, "width_mm": 180}}).json()
    spots = {(c["remnant_id"], c["x_mm"], c["y_mm"]) for c in many["candidates"]}
    assert many["covered_quantity"] == 4 and len(spots) == 4
    premium = client.post(f"{API}/cutting/candidates", json={"dataset_id": "ws", "material_id": "clear-4",
                                                             "premium": True, "quantity": 10,
                                                             "dimensions": {"length_mm": 280, "width_mm": 280}}).json()
    assert 0 < premium["covered_quantity"] < 10
    assert "R3" not in {c["remnant_id"] for c in premium["candidates"]}  # defect piece refused for premium
    assert {"INSUFFICIENT_JOINT_CAPACITY", "PREMIUM_ON_DEFECT"} <= set(premium["reason_codes"])
    huge = client.post(f"{API}/cutting/candidates", json={"dataset_id": "ws", "material_id": "grey-8",
                                                          "dimensions": {"length_mm": 100, "width_mm": 100}}).json()
    assert huge["reason_codes"] == ["UNKNOWN_MATERIAL"]
    temp = client.post(f"{API}/cutting/candidates", json={"dataset_id": "ws", "material_id": "temp-6",
                                                          "dimensions": {"length_mm": 402, "width_mm": 598}}).json()
    assert temp["candidates"][0]["remnant_id"] == "T1" and temp["candidates"][0]["rot"] == 1
    # after committing a plan that uses R1, the no-replan mode excludes the whole piece
    plan = solve(app, client)
    assert commit(client, "ws", plan).status_code == 200
    used = {p["remnant_id"] for p in plan["placements"] if p["remnant_id"] != "NEW"}
    free = client.post(f"{API}/cutting/candidates", json={"dataset_id": "ws", "material_id": "clear-4",
                                                          "dimensions": {"length_mm": 100, "width_mm": 100}}).json()
    assert not ({c["remnant_id"] for c in free["candidates"]} & used)


def test_failed_job_keeps_previous_active_plan(app_client):
    app, client = app_client
    register(app, "ws", small_snapshot())
    plan = solve(app, client)
    assert commit(client, "ws", plan).status_code == 200
    app.state.job_submitter = InlineJobSubmitter(app, fail=True)
    job = client.post(f"{API}/cutting/solve", json={"dataset_id": "ws"}).json()
    assert job["state"] == "failed"
    active = client.get(f"{API}/plans/active", params={"dataset_id": "ws"}).json()
    assert (active["plan_id"], active["status"]) == (plan["plan_id"], "committed")


def test_layout_and_export_contracts(app_client):
    app, client = app_client
    register(app, "ws", small_snapshot())
    plan = solve(app, client)
    layout = client.get(f"{API}/plans/{plan['plan_id']}/layout", params={"dataset_id": "ws"}).json()
    temp = [r for r in layout["remnants"] if r["tempered"]]
    assert temp and temp[0]["trim_mm"] == 0 and temp[0]["parts"][0]["x_mm"] == 0
    normal = next(r for r in layout["remnants"] if not r["tempered"])
    assert normal["trim_mm"] == 5 and normal["gap_mm"] == 3
    export = client.get(f"{API}/plans/{plan['plan_id']}/export", params={"dataset_id": "ws"}).json()
    assert export["header"] == ["part_id", "remnant_id", "x_mm", "y_mm", "rot"]
    assert [r["part_id"] for r in export["rows"]] == ["P1", "P2", "P3", "P4", "P5", "P6"]
    p6 = export["rows"][5]
    assert p6 == {"part_id": "P6", "remnant_id": "NEW", "x_mm": "", "y_mm": "", "rot": ""}
    assert export["metrics"]["new_reasons"]["P6"] == "SIZE_TOO_LARGE"
    assert export["validation"]["valid"]
