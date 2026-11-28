
from glassflow.contracts.cutting import CutPlan, Placement, SolverConfig
from glassflow.modules.cutting.conversion import input_from_snapshot, to_assignment
from glassflow.modules.cutting.geometry import validate_plan
from glassflow.modules.cutting.metrics import compute_metrics
from glassflow.modules.cutting.sale_readiness import ensure_sale_readiness

from .conftest import make_snapshot


def case(extra_size=220):
    snapshot = make_snapshot([(f'candidate-{i}', 'clear-4', 110, 110, False) for i in range(5)] +
        [('other', 'clear-4', extra_size, extra_size, False)], [('part', 'order', 'clear-4', 100, 100, False)])
    data = input_from_snapshot(snapshot, config=SolverConfig(profile='quick', minimum_free_remnants=5))
    placements = [Placement(part_id='part', remnant_id='candidate-0', x_mm=5, y_mm=5, rot=0)]
    report = validate_plan(snapshot, [to_assignment(p) for p in placements])
    metrics, free = compute_metrics(snapshot, report)
    baseline = CutPlan(dataset_id=data.dataset_id, plan_id='baseline', revision=1, status='validated',
        placements=placements, metrics=metrics, free_original_remnant_ids=free, search_status='feasible')
    return data, baseline, {f'candidate-{i}' for i in range(5)}


def test_ready_plan_never_runs_search(monkeypatch):
    from glassflow.modules.cutting import sale_readiness
    data, baseline, eligible = case()
    eligible.add('other')
    def forbidden(*args, **kwargs):
        raise AssertionError('Already ready plan must not be recalculated')
    monkeypatch.setattr(sale_readiness._SaleSolver, '__init__', forbidden)
    result = ensure_sale_readiness(data, baseline, eligible, 'registry1')
    assert result.status == 'ready_unchanged' and not result.search_performed
    assert result.baseline == baseline and result.alternative is None


def test_many_free_but_fewer_than_five_buyer_eligible_is_evidence_shortage():
    data, baseline, eligible = case()
    result = ensure_sale_readiness(data, baseline, set(list(eligible)[:4]), 'registry1')
    assert result.status == 'evidence_shortage' and not result.search_performed


def test_exactly_five_eligible_finds_area_neutral_separate_alternative():
    data, baseline, eligible = case()
    result = ensure_sale_readiness(data, baseline, eligible, 'registry1', budget_seconds=3)
    assert result.status == 'ready_alternative', result
    assert result.alternative.metrics.covered_area_mm2 == baseline.metrics.covered_area_mm2
    assert result.delta_area_mm2 == 0 and result.baseline == baseline
    assert result.alternative.placements[0].remnant_id == 'other'
    assert len(result.candidate_free_eligible_ids) == 5


def test_area_loss_is_separate_and_explicit_baseline_is_never_replaced():
    data, baseline, eligible = case(extra_size=90)
    result = ensure_sale_readiness(data, baseline, eligible, 'registry1', budget_seconds=2)
    assert result.status == 'tradeoff_available', result
    assert result.alternative is None and result.tradeoff is not None
    assert result.delta_area_mm2 == -10000 and result.baseline == baseline
    assert len(result.candidate_free_eligible_ids) == 5


def test_inventory_and_registry_fingerprints_change_and_reserved_is_not_eligible():
    data, baseline, eligible = case()
    first = ensure_sale_readiness(data, baseline, eligible | {'other'}, 'registry1')
    second = ensure_sale_readiness(data, baseline, eligible | {'other'}, 'registry2')
    assert first.registry_fingerprint != second.registry_fingerprint
    changed = data.model_copy(deep=True)
    changed.remnants[1].status = 'reserved'
    changed.remnants[1].version += 1
    result = ensure_sale_readiness(changed, baseline, eligible, 'registry2')
    assert result.status == 'evidence_shortage'
    assert result.inventory_fingerprint != first.inventory_fingerprint


def test_changed_dimensions_make_old_plan_stale_and_cancel_preserves_it():
    data, baseline, eligible = case()
    changed = data.model_copy(deep=True)
    changed.parts[0].dimensions.length_mm = 101
    assert ensure_sale_readiness(changed, baseline, eligible, 'registry1').status == 'stale'
    class Cancelled:
        def cancelled(self):return True
    result = ensure_sale_readiness(data, baseline, eligible, 'registry1', context=Cancelled())
    assert result.status == 'cancelled' and result.baseline == baseline and not result.search_performed


def test_nonoriginal_and_unknown_ids_do_not_create_buyer_eligible_stock():
    data, baseline, eligible = case()
    data.remnants[1].original = False
    result = ensure_sale_readiness(data, baseline, eligible | {'invented-id'}, 'registry1')
    assert result.status == 'evidence_shortage'
    assert 'invented-id' not in result.eligible_original_ids


def test_requested_lock_is_not_silently_dropped_to_make_cards():
    data, baseline, eligible = case()
    lock = baseline.placements[0].model_copy(update={'lock_kind': 'assignment'})
    data.locks = [lock]
    baseline.requested_locks = [lock]
    result = ensure_sale_readiness(data, baseline, eligible, 'registry1', budget_seconds=2)
    assert result.status == 'limited'
    assert result.alternative is result.tradeoff is None and result.baseline == baseline


def test_replaced_ids_and_reversed_input_use_ordinary_domain_data():
    data, baseline, eligible = case()
    names = {r.remnant_id: 'changed-' + str(i*13+7) for i, r in enumerate(reversed(data.remnants))}
    for r in data.remnants:
        r.remnant_id = names[r.remnant_id]
    data.remnants.reverse()
    data.parts[0].part_id = 'new-part-1029'
    baseline.placements[0].part_id = 'new-part-1029'
    baseline.placements[0].remnant_id = names[baseline.placements[0].remnant_id]
    result = ensure_sale_readiness(data, baseline, {names[x] for x in eligible}, 'new-registry')
    assert result.status == 'ready_alternative'
    assert result.alternative.placements[0].remnant_id == names['other']


def test_invalid_budget_rejected_without_mutation():
    import pytest
    data, baseline, eligible = case()
    for invalid in [0, -1, float('nan'), float('inf'), 31]:
        with pytest.raises(ValueError):
            ensure_sale_readiness(data, baseline, eligible, 'registry1', budget_seconds=invalid)
