"""Solver behaviour: tempered matching optimality, first plan, cancel/limit (T14), locks (T16),
five free originals (T17), determinism of the fixed-work profile, open pack quick plan."""

import itertools
import time

from glassflow.contracts.cutting import Placement, SolverConfig
from glassflow.modules.cutting.conversion import input_from_snapshot
from glassflow.modules.cutting.domain import NEW, Assignment
from glassflow.modules.cutting.engine import CuttingEngine
from glassflow.modules.cutting.geometry import validate_plan
from glassflow.modules.cutting.solver import CuttingSolver, SolverSettings, score, solve

from .conftest import make_snapshot, official_module, official_rows


def test_tempered_matching_is_maximum_weight():
    # Greedy-by-area would put P1 (largest) on T1 and lose P2; the optimum covers P2 on T1 and P1 on T2.
    snap = make_snapshot(
        [("T1", "temp-6", 600, 400, False), ("T2", "temp-6", 602, 401, False), ("T3", "temp-6", 300, 300, False)],
        [("P1", "O1", "temp-6", 601, 401, False), ("P2", "O2", "temp-6", 599, 399, False),
         ("P3", "O3", "temp-6", 300, 301, False), ("P4", "O4", "temp-6", 301, 299, False)])
    result = CuttingSolver(snap, SolverSettings(profile="quick")).tempered_matching()
    covered = sum(snap.parts[p].area for p in result)
    best = 0
    remnants = list(snap.remnants)
    for perm in itertools.permutations(list(snap.parts) + [None] * 3, len(remnants)):
        area = 0
        for rid, pid in zip(remnants, perm, strict=True):
            if pid is None:
                continue
            p, r = snap.parts[pid], snap.remnants[rid]
            if (abs(p.length_mm - r.length_mm) <= 2 and abs(p.width_mm - r.width_mm) <= 2) or (
                    abs(p.length_mm - r.width_mm) <= 2 and abs(p.width_mm - r.length_mm) <= 2):
                area += p.area
        best = max(best, area)
    assert covered == best and len({a.remnant_id for a in result.values()}) == len(result)


def test_first_plan_on_open_pack_is_fast_complete_and_officially_valid(open_snapshot):
    started = time.perf_counter()
    outcome = solve(open_snapshot, SolverSettings(profile="quick", time_limit_seconds=5, workers=1))
    elapsed = time.perf_counter() - started
    rows = outcome.rows(open_snapshot)
    assert validate_plan(open_snapshot, rows).valid
    assert len(rows) == 298 and elapsed < 5.0  # TZ 27 target: first valid plan <= 5 s (measured here)
    official = official_module()
    stock, orders, mats = official_rows(open_snapshot)
    sol = [{"part_id": a.part_id, "remnant_id": a.remnant_id, "x_mm": "" if a.x_mm is None else str(a.x_mm),
            "y_mm": "" if a.y_mm is None else str(a.y_mm), "rot": "" if a.rot is None else str(a.rot)} for a in rows]
    _, _, ok, bad = official.check(stock, orders, sol, mats)
    assert bad == [] and sum(open_snapshot.parts[p].area for p in ok) == outcome.covered_area
    assert outcome.covered_area / open_snapshot.total_part_area > 0.55


class CancelAfterFirst:
    def __init__(self):
        self.incumbents = []
        self.calls = 0

    def cancelled(self):
        return bool(self.incumbents)

    def progress(self, stage, completed, total):
        self.calls += 1

    def incumbent(self, outcome):
        self.incumbents.append(outcome)


def test_t14_cancel_keeps_last_valid_incumbent_and_no_false_optimal(open_snapshot):
    cb = CancelAfterFirst()
    outcome = solve(open_snapshot, SolverSettings(profile="extended", time_limit_seconds=600), callbacks=cb)
    assert cb.incumbents and outcome.stop_reason == "cancelled" and outcome.search_status == "limited"
    assert validate_plan(open_snapshot, outcome.rows(open_snapshot)).valid
    assert outcome.covered_area >= cb.incumbents[0].covered_area


def test_t14_time_limit_reports_limited_not_infeasible(open_snapshot):
    outcome = solve(open_snapshot, SolverSettings(profile="standard", time_limit_seconds=4))
    assert outcome.stop_reason == "time_limit" and outcome.search_status == "limited"
    assert validate_plan(open_snapshot, outcome.rows(open_snapshot)).valid


def test_t14_engine_publishes_only_validated_incumbents(open_snapshot):
    published = []

    class Ctx:
        def cancelled(self):
            return len(published) >= 2

        def progress(self, *a):
            pass

        def incumbent(self, plan):
            published.append(plan)

    plan = CuttingEngine().solve(input_from_snapshot(open_snapshot, config=SolverConfig(
        profile="standard", time_limit_seconds=60)), Ctx())
    assert published and all(p.status == "validated" and p.metrics.invalid == 0 for p in published)
    assert plan.status == "validated" and plan.search_status == "limited"


def test_t16_locks_are_respected_and_conflicts_reported():
    snap = make_snapshot([("R1", "clear-4", 400, 300, False), ("R2", "clear-4", 400, 300, False)],
                         [("P1", "O1", "clear-4", 200, 100, False), ("P2", "O1", "clear-4", 150, 100, False),
                          ("P3", "O2", "clear-4", 380, 280, False)])
    locks = [Assignment("P1", "R2", 100, 150, 0, "placement"), Assignment("P2", "R2", lock_kind="assignment")]
    outcome = solve(snap, SolverSettings(profile="standard", time_limit_seconds=10, minimum_free_remnants=0),
                    locks=locks)
    a = outcome.assignments
    assert (a["P1"].remnant_id, a["P1"].x_mm, a["P1"].y_mm, a["P1"].rot) == ("R2", 100, 150, 0)
    assert a["P2"].remnant_id == "R2" and a["P3"].remnant_id == "R1"
    assert validate_plan(snap, outcome.rows(snap), locks=locks).valid
    # impossible lock (part does not fit the remnant) -> explicit conflict, plan stays valid
    bad = solve(snap, SolverSettings(profile="quick", minimum_free_remnants=0),
                locks=[Assignment("P3", "R2", 5, 5, 1, "placement")])
    assert any(c.code == "LOCK_CONFLICT" for c in bad.conflicts)
    assert validate_plan(snap, bad.rows(snap)).valid


def test_t16_excluded_remnant_is_not_used():
    snap = make_snapshot([("R1", "clear-4", 400, 300, False), ("R2", "clear-4", 400, 300, False)],
                         [("P1", "O1", "clear-4", 380, 280, False)])
    outcome = solve(snap, SolverSettings(profile="standard", time_limit_seconds=5, minimum_free_remnants=0),
                    unavailable=["R1"])
    assert outcome.assignments["P1"].remnant_id == "R2"


def test_t17_five_free_constraint_and_exact_area_loss_reported():
    # 6 identical remnants, 6 parts that each fill one remnant: with >=5 free only 1 can be used.
    remnants = [(f"R{i}", "clear-4", 300, 300, False) for i in range(6)]
    parts = [(f"P{i}", f"O{i}", "clear-4", 290, 290, False) for i in range(6)]
    snap = make_snapshot(remnants, parts)
    outcome = solve(snap, SolverSettings(profile="standard", time_limit_seconds=20, minimum_free_remnants=5))
    assert outcome.meets_min_free and outcome.free_original == 5 and len(outcome.assignments) == 1
    assert outcome.stats["unconstrained_best_area_mm2"] == 6 * 290 * 290
    assert outcome.stats["five_free_area_loss_mm2"] == 5 * 290 * 290


def test_fixed_work_profile_is_deterministic():
    """Same seed + fixed work => identical plan. Small CP-SAT deterministic budgets keep the test short;
    both runs must finish by work counters (``completed``), never by the wall-clock safety cap."""
    remnants = [(f"R{i}", "clear-4", 500 + 37 * i, 400 + 23 * i, i % 3 == 0) for i in range(4)]
    parts = [(f"P{j}", f"O{j % 4}", "clear-4", 100 + 31 * (j % 7), 80 + 17 * (j % 5), j % 4 == 0) for j in range(12)]
    snap = make_snapshot(remnants, parts)
    s = SolverSettings(profile="standard", time_limit_seconds=600, fixed_work=True, workers=1,
                       minimum_free_remnants=1, seed=7, pricing_seconds=0.05, lns_seconds=0.1)
    a, b = solve(snap, s), solve(snap, s)
    assert a.stop_reason == b.stop_reason == "completed"
    assert a.assignments == b.assignments and a.covered_area == b.covered_area
    assert validate_plan(snap, a.rows(snap)).valid


def test_engine_keep_committed_mode_keeps_whole_pieces_untouched():
    snap = make_snapshot([("R1", "clear-4", 400, 300, False), ("R2", "clear-4", 400, 300, False)],
                         [("P1", "O1", "clear-4", 100, 100, False), ("P2", "O2", "clear-4", 100, 100, False)])
    data = input_from_snapshot(snap, config=SolverConfig(profile="quick", minimum_free_remnants=0),
                               occupied_remnant_ids=["R1"],
                               locks=[Placement(part_id="P1", remnant_id="R1", x_mm=5, y_mm=5, rot=0,
                                                lock_kind="placement")])
    plan = CuttingEngine().solve(data, None)
    by_part = {p.part_id: p for p in plan.placements}
    assert (by_part["P1"].remnant_id, by_part["P1"].x_mm) == ("R1", 5)
    assert by_part["P2"].remnant_id == "R2"  # never added into the occupied production piece
    assert plan.status == "validated"


def test_empty_and_impossible_inputs_give_complete_new_plans():
    no_stock = make_snapshot([], [("P1", "O1", "clear-4", 100, 100, False)])
    outcome = solve(no_stock, SolverSettings(profile="standard", time_limit_seconds=5))
    assert outcome.rows(no_stock) == [Assignment("P1", NEW)] and outcome.new_reasons == {"P1": "MATERIAL_MISMATCH"}
    no_parts = make_snapshot([("R1", "clear-4", 100, 100, False)], [])
    assert solve(no_parts, SolverSettings(profile="quick")).rows(no_parts) == []
    too_big = make_snapshot([("R1", "clear-4", 100, 100, False)], [("P1", "O1", "clear-4", 95, 50, True)])
    assert solve(too_big, SolverSettings(profile="quick")).new_reasons == {"P1": "SIZE_TOO_LARGE"}


def test_score_formula():
    assert score(0.50, 0) == 0 and score(0.65, 0) == 20 and score(0.80, 0) == 20
    assert abs(score(0.589523, 0) - 11.93640) < 1e-4
    assert score(0.65, 30) == 14 and score(0.4, 3) == 0
