from glassflow.contracts.cutting import Placement, SolverConfig
from glassflow.modules.cutting.conversion import input_from_snapshot
from glassflow.modules.cutting.engine import CuttingEngine
from glassflow.modules.cutting.geometry import validate_plan
from glassflow.modules.cutting.solver import CuttingSolver, SolverSettings

from .conftest import make_snapshot


def tight():
    return make_snapshot([(f'piece-{i}', 'clear-4', 110, 110, False) for i in range(6)],
        [(f'part-{i}', f'order-{i}', 'clear-4', 100, 100, False) for i in range(6)])


def test_short_budget_keeps_a_complete_plan_with_five_free_originals():
    snapshot = tight()
    result = CuttingSolver(snapshot, SolverSettings(profile='quick',time_limit_seconds=.00001,
        minimum_free_remnants=5)).run()
    assert validate_plan(snapshot,result.rows(snapshot)).valid
    assert result.meets_min_free and result.free_original>=5
    assert result.covered_area==0


def test_cancel_before_greedy_preserves_initial_complete_incumbent():
    snapshot = tight()
    class Cancelled:
        def cancelled(self):return True
        def progress(self,*args):pass
        def incumbent(self,result):pass
    result = CuttingSolver(snapshot, SolverSettings(profile='quick',time_limit_seconds=1,
        minimum_free_remnants=5),callbacks=Cancelled()).run()
    assert result.free_original>=5 and validate_plan(snapshot,result.rows(snapshot)).valid
    assert result.stop_reason=='cancelled'


def test_initial_seed_never_publishes_missing_requested_lock():
    snapshot = tight()
    task = input_from_snapshot(snapshot,config=SolverConfig(profile='quick',time_limit_seconds=1,
        minimum_free_remnants=5),locks=[Placement(part_id='part-0',remnant_id='piece-0',lock_kind='assignment')])
    emitted=[]
    class Callback:
        def cancelled(self):return False
        def progress(self,*args):pass
        def incumbent(self,plan):emitted.append(plan)
    CuttingEngine().solve(task,Callback())
    assert all(any(p.part_id=='part-0' and p.remnant_id=='piece-0' for p in plan.placements) for plan in emitted)


def test_insufficient_available_originals_never_claims_full_feasibility_or_publishes():
    snapshot = make_snapshot([('only','clear-4',110,110,False)],[('p','o','clear-4',100,100,False)])
    task = input_from_snapshot(snapshot,config=SolverConfig(profile='quick',time_limit_seconds=1,
        minimum_free_remnants=5))
    emitted=[]
    class Callback:
        def cancelled(self):return False
        def progress(self,*args):pass
        def incumbent(self,plan):emitted.append(plan)
    plan = CuttingEngine().solve(task,Callback())
    assert not emitted
    assert plan.search_status=='limited' and plan.evidence['minimum_free_remnants_met'] is False


def test_original_quick_coverage_does_not_regress(open_snapshot):
    task = input_from_snapshot(open_snapshot,config=SolverConfig(profile='quick',time_limit_seconds=5,workers=1))
    plan = CuttingEngine().solve(task)
    assert plan.status=='validated' and plan.metrics.invalid==plan.metrics.missing==0
    assert plan.metrics.covered_area_mm2>=104_844_000  # Existing quick baseline55.8080067%.
    assert plan.metrics.free_original_remnants>=5


def test_excluded_originals_do_not_make_an_infeasible_initial_seed_publishable():
    snapshot = tight()
    task = input_from_snapshot(snapshot,config=SolverConfig(profile='quick',time_limit_seconds=1,
        minimum_free_remnants=5),unavailable_remnant_ids=['piece-0','piece-1'])
    emitted=[]
    class Callback:
        def cancelled(self):return False
        def progress(self,*args):pass
        def incumbent(self,plan):emitted.append(plan)
    plan = CuttingEngine().solve(task,Callback())
    assert not emitted and plan.evidence['minimum_free_remnants_met'] is False
    assert not {'piece-0','piece-1'} & set(plan.free_original_remnant_ids)
    assert plan.metrics.free_original_remnants == len(plan.free_original_remnant_ids) <= 4


def test_metrics_exclude_occupied_and_unavailable_even_when_raw_status_available():
    from glassflow.modules.cutting.domain import Assignment
    from glassflow.modules.cutting.metrics import compute_metrics

    snapshot = tight()
    report = validate_plan(snapshot,[Assignment(pid,'NEW') for pid in snapshot.parts])
    metrics, free = compute_metrics(snapshot,report,
        excluded_remnant_ids={'piece-0','piece-1','unknown-id'})
    assert set(free)=={'piece-2','piece-3','piece-4','piece-5'}
    assert metrics.free_original_remnants==4
