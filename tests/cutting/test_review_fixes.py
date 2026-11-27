"""Regressions for review CLAUDE_2_REVIEW_2026-11-27: C2-F1 (lock conflicts) and C2-F2 (live free pieces).

All data here is synthetic TEST data.
"""

import pytest

from glassflow.contracts.common import Dimensions
from glassflow.contracts.cutting import (
    CommitPlan,
    ConsumeRequest,
    DraftEdit,
    DraftRequest,
    Placement,
    ReleaseRequest,
    ReserveRequest,
    SolverConfig,
    SolveRequest,
    WithdrawRequest,
)
from glassflow.modules.cutting.engine import CuttingEngine
from glassflow.modules.cutting.service import CuttingError, CuttingService
from glassflow.modules.cutting.uow import read_session, write_transaction

from .conftest import make_snapshot, register

QUICK = SolverConfig(profile="quick", minimum_free_remnants=0)


def run(app, fn, write=True):
    ctx = write_transaction if write else read_session
    with ctx(app.state.session_factory) as session:
        return fn(CuttingService(session))


def solve_and_store(app, dataset, locks=(), config=QUICK, **kw):
    data = run(app, lambda s: s.solve_input(SolveRequest(dataset_id=dataset, locks=list(locks), config=config, **kw)),
               write=False)
    plan = CuttingEngine().solve(data, None)
    stored = run(app, lambda s: s.store_solver_plan(dataset, plan))
    return data, plan, stored


def versions(app, dataset, plan):
    used = {p.remnant_id for p in plan.placements if p.remnant_id != "NEW"}
    return {rid: run(app, lambda s, r=rid: s.get_remnant(dataset, r).version, write=False) for rid in used}


def try_commit(app, dataset, plan):
    return run(app, lambda s: s.commit(plan.plan_id, CommitPlan(
        dataset_id=dataset, plan_revision=plan.revision, expected_remnant_versions=versions(app, dataset, plan))))


# ------------------------------------------------------------------------------------------ C2-F1
def reviewer_snapshot():
    return make_snapshot([("R1", "clear-4", 100, 100, False), ("R2", "clear-4", 400, 300, False)],
                         [("P1", "O1", "clear-4", 200, 100, False)])


def test_f1_reviewer_case_impossible_assignment_is_never_validated_or_committable(app_client):
    app, _ = app_client
    register(app, "ws", reviewer_snapshot())
    lock = Placement(part_id="P1", remnant_id="R1", lock_kind="assignment")
    data, plan, stored = solve_and_store(app, "ws", [lock])
    engine_verdict = CuttingEngine().validate(data, plan)
    # engine output, engine.validate and the stored revision now agree
    assert plan.status == "invalid" and not engine_verdict.valid
    assert {i.code for i in plan.issues} >= {"LOCK_CONFLICT"}
    assert stored.status == "invalid"
    codes = {i.code for i in stored.issues}
    assert "LOCK_VIOLATED" in codes and "LOCK_CONFLICT" in codes
    assert [lk.model_dump() for lk in stored.requested_locks] == [lock.model_dump()]
    reloaded = run(app, lambda s: s.get_plan("ws", stored.plan_id), write=False)
    assert reloaded.status == "invalid" and reloaded.requested_locks == stored.requested_locks
    assert {i.code for i in reloaded.issues} >= {"LOCK_VIOLATED", "LOCK_CONFLICT"}
    with pytest.raises(CuttingError) as exc:
        try_commit(app, "ws", stored)
    assert exc.value.status == 409
    with pytest.raises(CuttingError) as exc:
        run(app, lambda s: s.export("ws", stored.plan_id), write=False)
    assert exc.value.code == "PLAN_INVALID"
    # re-validation keeps it invalid while the constraint exists
    assert not run(app, lambda s: s.validate("ws", stored.plan_id)).valid


def test_f1_explicit_unlock_creates_committable_revision(app_client):
    app, _ = app_client
    register(app, "ws", reviewer_snapshot())
    _, _, stored = solve_and_store(app, "ws", [Placement(part_id="P1", remnant_id="R1", lock_kind="assignment")])
    draft = run(app, lambda s: s.draft(stored.plan_id, DraftRequest(
        dataset_id="ws", base_revision=stored.revision, edits=[DraftEdit(part_id="P1", action="unlock")])))
    assert draft.validation.valid and draft.plan.status == "draft" and draft.plan.requested_locks == []
    result = try_commit(app, "ws", draft.plan)
    assert result.plan.status == "committed"
    export = run(app, lambda s: s.export("ws", draft.plan.plan_id), write=False)
    assert export.validation.valid and export.rows[0].remnant_id == "R2"
    # the original revision keeps its constraint (history is immutable)
    assert run(app, lambda s: s.get_plan("ws", stored.plan_id, stored.revision), write=False).requested_locks


def test_f1_requested_lock_survives_edits_and_blocks_moves(app_client):
    app, _ = app_client
    register(app, "ws", make_snapshot([("R1", "clear-4", 400, 300, False), ("R2", "clear-4", 400, 300, False)],
                                      [("P1", "O1", "clear-4", 100, 100, False), ("P2", "O1", "clear-4", 100, 100, False)]))
    lock = Placement(part_id="P1", remnant_id="R2", x_mm=50, y_mm=60, rot=0, lock_kind="placement")
    _, plan, stored = solve_and_store(app, "ws", [lock])
    assert plan.status == "validated" and stored.status == "validated"
    p1 = next(p for p in stored.placements if p.part_id == "P1")
    assert (p1.remnant_id, p1.x_mm, p1.y_mm, p1.lock_kind) == ("R2", 50, 60, "placement")
    with pytest.raises(CuttingError) as exc:
        run(app, lambda s: s.draft(stored.plan_id, DraftRequest(dataset_id="ws", base_revision=stored.revision, edits=[
            DraftEdit(part_id="P1", action="move", remnant_id="R2", x_mm=5, y_mm=5, rot=0)])))
    assert exc.value.code == "PART_LOCKED"
    # editing another part keeps the requested lock on the new revision
    p2 = next(p for p in stored.placements if p.part_id == "P2")
    edited = run(app, lambda s: s.draft(stored.plan_id, DraftRequest(dataset_id="ws", base_revision=stored.revision,
                                                                       edits=[DraftEdit(part_id="P2", action="unplace")])))
    assert p2.remnant_id != "NEW" and edited.plan.requested_locks == stored.requested_locks
    assert try_commit(app, "ws", edited.plan).plan.status == "committed"


def test_f1_coordinate_conflict_between_locks(app_client):
    app, _ = app_client
    register(app, "ws", make_snapshot([("R1", "clear-4", 400, 300, False)],
                                      [("P1", "O1", "clear-4", 100, 100, False), ("P2", "O1", "clear-4", 100, 100, False)]))
    locks = [Placement(part_id="P1", remnant_id="R1", x_mm=5, y_mm=5, rot=0, lock_kind="placement"),
             Placement(part_id="P2", remnant_id="R1", x_mm=50, y_mm=50, rot=0, lock_kind="placement")]
    data, plan, stored = solve_and_store(app, "ws", locks)
    assert plan.status == "invalid" and not CuttingEngine().validate(data, plan).valid
    assert stored.status == "invalid" and "LOCK_VIOLATED" in {i.code for i in stored.issues}
    # geometry of whatever is placed is still clean: no overlap is ever produced to "satisfy" both locks
    assert not {"OVERLAP", "GAP_VIOLATION"} & {i.code for i in stored.issues}
    with pytest.raises(CuttingError):
        try_commit(app, "ws", stored)


def test_f1_lock_out_of_bounds_and_on_unavailable_piece(app_client):
    app, _ = app_client
    register(app, "ws", make_snapshot([("R1", "clear-4", 400, 300, False), ("R2", "clear-4", 400, 300, False)],
                                      [("P1", "O1", "clear-4", 100, 100, False)]))
    _, plan, stored = solve_and_store(app, "ws", [Placement(part_id="P1", remnant_id="R1", x_mm=0, y_mm=0, rot=0,
                                                            lock_kind="placement")])
    assert plan.status == "invalid" and stored.status == "invalid"
    run(app, lambda s: s.withdraw("R2", WithdrawRequest(dataset_id="ws", expected_version=0, reason="скол")))
    _, plan2, stored2 = solve_and_store(app, "ws", [Placement(part_id="P1", remnant_id="R2", lock_kind="assignment")])
    assert plan2.status == "invalid" and stored2.status == "invalid"
    assert any(i.code == "LOCK_CONFLICT" and i.remnant_id == "R2" for i in stored2.issues)


def test_f1_mutually_incompatible_assignment_locks_on_tempered(app_client):
    app, _ = app_client
    register(app, "ws", make_snapshot([("T1", "temp-6", 600, 400, False)],
                                      [("P1", "O1", "temp-6", 600, 400, False), ("P2", "O2", "temp-6", 601, 399, False)]))
    locks = [Placement(part_id="P1", remnant_id="T1", lock_kind="assignment"),
             Placement(part_id="P2", remnant_id="T1", lock_kind="placement")]
    data, plan, stored = solve_and_store(app, "ws", locks)
    assert plan.status == "invalid" and not CuttingEngine().validate(data, plan).valid
    assert stored.status == "invalid"
    placed = [p for p in stored.placements if p.remnant_id == "T1"]
    assert len(placed) == 1  # never two parts on one tempered piece


def test_f1_satisfiable_tempered_placement_lock_is_valid(app_client):
    app, _ = app_client
    register(app, "ws", make_snapshot([("T1", "temp-6", 400, 600, False)], [("P1", "O1", "temp-6", 600, 400, False)]))
    data, plan, stored = solve_and_store(app, "ws", [Placement(part_id="P1", remnant_id="T1", lock_kind="placement")])
    assert plan.status == "validated" and CuttingEngine().validate(data, plan).valid and stored.status == "validated"
    assert try_commit(app, "ws", stored).plan.status == "committed"


def test_f1_invalid_incumbents_are_not_published(app_client):
    app, _ = app_client
    register(app, "ws", reviewer_snapshot())
    data = run(app, lambda s: s.solve_input(SolveRequest(
        dataset_id="ws", locks=[Placement(part_id="P1", remnant_id="R1", lock_kind="assignment")],
        config=SolverConfig(profile="standard", time_limit_seconds=5, minimum_free_remnants=0))), write=False)
    published = []

    class Ctx:
        def cancelled(self):
            return False

        def progress(self, *args):
            pass

        def incumbent(self, plan):
            published.append(plan)

    final = CuttingEngine().solve(data, Ctx())
    assert final.status == "invalid" and published == []


# ------------------------------------------------------------------------------------------ C2-F2
def five_free_snapshot():
    remnants = [("RA", "clear-4", 400, 300, False)] + [(f"F{i}", "clear-4", 300, 300, False) for i in range(5)]
    return make_snapshot(remnants, [("P1", "O1", "clear-4", 380, 280, False)])


def plan_using_ra(app):
    _, _, stored = solve_and_store(app, "ws", config=SolverConfig(profile="quick", minimum_free_remnants=5))
    assert {p.remnant_id for p in stored.placements} == {"RA"}
    assert stored.free_original_remnant_ids == [f"F{i}" for i in range(5)]
    return stored


def reserve_quote(app, rid):
    version = run(app, lambda s: s.get_remnant("ws", rid).version, write=False)
    return run(app, lambda s: s.reserve(rid, ReserveRequest(
        dataset_id="ws", expected_version=version, owner_context="quote:test", material_id="clear-4",
        dimensions=Dimensions(length_mm=50, width_mm=50))))


def test_f2_reviewer_case_reserved_piece_disappears_from_live_export(app_client):
    app, _ = app_client
    register(app, "ws", five_free_snapshot())
    plan = plan_using_ra(app)
    before = run(app, lambda s: s.export("ws", plan.plan_id), write=False)
    assert before.free_original_remnant_ids == [f"F{i}" for i in range(5)] and before.minimum_free_remnants_met
    assert not before.inventory_changed_since_plan and before.no_longer_free_remnant_ids == []
    reserve_quote(app, "F0")
    after = run(app, lambda s: s.export("ws", plan.plan_id), write=False)
    assert run(app, lambda s: s.get_remnant("ws", "F0").status, write=False) == "reserved"
    assert after.free_original_remnant_ids == ["F1", "F2", "F3", "F4"]
    assert after.metrics.free_original_remnants == 4
    assert after.minimum_free_remnants == 5 and after.minimum_free_remnants_met is False  # 5 -> 4
    assert after.inventory_changed_since_plan and after.inventory_version != after.plan_inventory_version
    assert after.no_longer_free_remnant_ids == ["F0"]
    assert after.plan_free_original_remnant_ids == [f"F{i}" for i in range(5)]  # history kept, labelled
    assert after.validation.valid and after.as_of
    # stored revision is history: unchanged list, but flagged as not current
    stored = run(app, lambda s: s.get_plan("ws", plan.plan_id), write=False)
    assert stored.free_original_remnant_ids == [f"F{i}" for i in range(5)] and stored.inventory_current is False
    check = run(app, lambda s: s.free_remnants("ws", plan.plan_id), write=False)
    assert [r.remnant_id for r in check.free_original] == ["F1", "F2", "F3", "F4"]
    assert check.count == 4 and not check.minimum_free_remnants_met and check.no_longer_free_remnant_ids == ["F0"]


def test_f2_release_withdraw_consume_keep_export_consistent(app_client):
    app, _ = app_client
    register(app, "ws", five_free_snapshot())
    plan = plan_using_ra(app)
    change = reserve_quote(app, "F1")
    run(app, lambda s: s.release_reservation(change.reservation.reservation_id, ReleaseRequest(
        dataset_id="ws", expected_version=change.reservation.version)))
    released = run(app, lambda s: s.export("ws", plan.plan_id), write=False)
    assert released.free_original_remnant_ids == [f"F{i}" for i in range(5)] and released.minimum_free_remnants_met
    run(app, lambda s: s.withdraw("F2", WithdrawRequest(dataset_id="ws", expected_version=s.get_remnant("ws", "F2").version,
                                                        reason="бой")))
    change = reserve_quote(app, "F3")
    run(app, lambda s: s.consume("F3", ConsumeRequest(dataset_id="ws", expected_version=change.remnant.version,
                                                      reservation_id=change.reservation.reservation_id)))
    live = run(app, lambda s: s.export("ws", plan.plan_id), write=False)
    assert live.free_original_remnant_ids == ["F0", "F1", "F4"]
    assert live.metrics.free_original_remnants == len(live.free_original_remnant_ids) == 3
    assert set(live.no_longer_free_remnant_ids) == {"F2", "F3"} and not live.minimum_free_remnants_met
    assert live.metrics.covered_area_mm2 == 380 * 280  # coverage of the plan itself is unaffected
    check = run(app, lambda s: s.free_remnants("ws", plan.plan_id), write=False)
    assert [r.remnant_id for r in check.free_original] == live.free_original_remnant_ids
    assert all(r.version == run(app, lambda s, x=r.remnant_id: s.get_remnant("ws", x).version, write=False)
               for r in check.free_original)


def test_f2_http_free_remnants_endpoint(app_client):
    app, client = app_client
    register(app, "ws", five_free_snapshot())
    plan = plan_using_ra(app)
    reserve_quote(app, "F4")
    body = client.get(f"/api/v1/plans/{plan.plan_id}/free-remnants", params={"dataset_id": "ws"}).json()
    assert body["count"] == 4 and body["minimum_free_remnants_met"] is False
    assert body["no_longer_free_remnant_ids"] == ["F4"]
    export = client.get(f"/api/v1/plans/{plan.plan_id}/export", params={"dataset_id": "ws"}).json()
    assert export["free_original_remnant_ids"] == [r["remnant_id"] for r in body["free_original"]]
