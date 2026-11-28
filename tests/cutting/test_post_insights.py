from glassflow.contracts.common import Dimensions
from glassflow.contracts.cutting import (
    CommitPlan,
    DraftEdit,
    DraftRequest,
    Placement,
    ReserveRequest,
    ScarcityRequest,
)
from glassflow.modules.cutting.service import CuttingService
from glassflow.modules.cutting.uow import read_session, write_transaction

from .conftest import make_snapshot, register


def imported(app, dataset, placements):
    with write_transaction(app.state.session_factory) as session:
        return CuttingService(session).import_plan(dataset, [dict(part_id=p.part_id, remnant_id=p.remnant_id,
            x_mm='' if p.x_mm is None else str(p.x_mm), y_mm='' if p.y_mm is None else str(p.y_mm),
            rot='' if p.rot is None else str(p.rot)) for p in placements])


def test_new_requirements_are_explicit_proposal_then_active_and_unknown_reason(app_client):
    app, client = app_client
    snapshot = make_snapshot([('piece', 'clear-4', 200, 200, False)],
        [('one', 'order', 'clear-4', 100, 80, False), ('two', 'order', 'clear-4', 100, 80, False)])
    register(app, 'new-scope', snapshot)
    plan = imported(app, 'new-scope', [Placement(part_id=p, remnant_id='NEW') for p in snapshot.parts])
    url = f'/api/v1/plans/{plan.plan_id}/new-requirements'
    result = client.get(url, params={'dataset_id': 'new-scope'}).json()
    assert result['scope'] == 'proposal' and not result['is_active']
    assert result['total_quantity'] == 2 and result['total_area_mm2'] == 16000
    assert result['rows'][0]['reason_code'] == 'NOT_PLACED_BY_EDIT'
    assert result['rows'][0]['part_ids'] == ['one', 'two']
    with write_transaction(app.state.session_factory) as session:
        CuttingService(session).commit(plan.plan_id, CommitPlan(dataset_id='new-scope',
            plan_revision=plan.revision, expected_remnant_versions={}))
    result = client.get(url, params={'dataset_id': 'new-scope'}).json()
    assert result['scope'] == 'active' and result['is_active']
    assert 'price' not in str(result) and 'sheet_count' not in str(result)


def test_margins_exact_gap_and_tempered_whole_piece(app_client):
    app, client = app_client
    snapshot = make_snapshot([('ordinary', 'clear-4', 220, 110, False), ('whole', 'temp-6', 100, 200, False)],
        [('a', 'o', 'clear-4', 100, 40, False), ('b', 'o', 'clear-4', 100, 40, False),
         ('t', 't', 'temp-6', 102, 199, False)])
    register(app, 'margins', snapshot)
    plan = imported(app, 'margins', [Placement(part_id='a', remnant_id='ordinary', x_mm=5, y_mm=5, rot=0),
        Placement(part_id='b', remnant_id='ordinary', x_mm=108, y_mm=5, rot=0),
        Placement(part_id='t', remnant_id='whole', x_mm=0, y_mm=0, rot=0)])
    result = client.get(f'/api/v1/plans/{plan.plan_id}/geometry-margins', params={'dataset_id': 'margins'}).json()
    rows = {r['part_id']: r for r in result['placements']}
    assert rows['a']['edge_clearance_mm'] == 5 and rows['a']['neighbor_clearance_mm'] == 3
    assert rows['a']['minimum_excess_mm'] == 0
    assert rows['t']['margin_kind'] == 'whole_piece_tolerance'
    assert rows['t']['dimension_deviation_mm'] == 2 and rows['t']['minimum_excess_mm'] == 0
    assert rows['t']['edge_clearance_mm'] is rows['t']['neighbor_clearance_mm'] is None


def scarcity_case(app, request_qty=1, pending_qty=1):
    snapshot = make_snapshot([('narrow', 'clear-4', 210, 110, False), ('square', 'clear-4', 160, 160, False)],
        [(f'known-{i}', 'known-order', 'clear-4', 200, 100, False) for i in range(pending_qty)])
    register(app, 'scarce', snapshot)
    return ScarcityRequest(dataset_id='scarce', material_id='clear-4', dimensions=Dimensions(length_mm=80,width_mm=40),
                           quantity=request_qty, budget_ms=3000)


def test_scarcity_proves_joint_capacity_and_preserves_normal_order(app_client):
    app, _ = app_client
    request = scarcity_case(app)
    with read_session(app.state.session_factory) as session:
        service = CuttingService(session)
        result = service.scarcity(request)
        if result.status == 'limited':
            # Cold native import may consume the analysis budget; ordinary
            # candidates remain available. A warm complete proof is required.
            result = service.scarcity(request)
        assert result.baseline.candidates[0].remnant_id == 'narrow'
        assert result.status == 'proved' and result.recommended_remnant_id == 'square'
        assert result.baseline_order_preserved
        assert result.explanations[0].pending_part_ids == ['known-0']
        assert {p.remnant_id for p in result.explanations[0].joint_witness} == {'narrow', 'square'}


def test_scarcity_quantity_two_uses_joint_witness(app_client):
    app, _ = app_client
    request = scarcity_case(app, request_qty=2)
    with read_session(app.state.session_factory) as session:
        result = CuttingService(session).scarcity(request)
    assert result.status == 'proved'
    assert len(result.explanations[0].request_part_ids) == 2
    assert len(result.explanations[0].joint_witness) == 3


def test_individual_fits_do_not_claim_whole_order_feasible(app_client):
    app, _ = app_client
    request = scarcity_case(app, pending_qty=2)
    with read_session(app.state.session_factory) as session:
        result = CuttingService(session).scarcity(request)
    assert result.status == 'no_proof' and not result.explanations


def test_scarcity_low_budget_has_no_invented_advice(app_client):
    app, _ = app_client
    request = scarcity_case(app).model_copy(update={'budget_ms': 1})
    with read_session(app.state.session_factory) as session:
        result = CuttingService(session).scarcity(request)
    assert result.status in {'limited', 'proved'}
    if result.status == 'limited':
        assert result.recommended_remnant_id is None and not result.explanations


def test_invalid_plan_does_not_become_new_procurement(app_client):
    app, client = app_client
    register(app, 'bad-new', make_snapshot([('piece','clear-4',200,200,False)],
        [('part','order','clear-4',100,100,False)]))
    plan = imported(app,'bad-new',[Placement(part_id='part',remnant_id='piece',x_mm=5,y_mm=5,rot=0)])
    with write_transaction(app.state.session_factory) as session:
        invalid = CuttingService(session).draft(plan.plan_id, DraftRequest(dataset_id='bad-new',
            base_revision=plan.revision, edits=[DraftEdit(part_id='part',x_mm=1,y_mm=5,rot=0,remnant_id='piece')]))
    result = client.get(f'/api/v1/plans/{invalid.plan.plan_id}/new-requirements',params={'dataset_id':'bad-new'})
    assert result.status_code == 409 and result.json()['code']=='PLAN_INVALID'


def test_reserved_alternative_invalidates_scarcity_advice(app_client):
    app, _ = app_client
    request = scarcity_case(app)
    with read_session(app.state.session_factory) as session:
        service = CuttingService(session)
        before = service.scarcity(request)
        if before.status == 'limited':
            before = service.scarcity(request)
    assert before.status=='proved'
    with write_transaction(app.state.session_factory) as session:
        CuttingService(session).reserve('square', ReserveRequest(dataset_id='scarce',expected_version=0,
            owner_context='another-manager',material_id='clear-4',dimensions=Dimensions(length_mm=80,width_mm=40)))
    with read_session(app.state.session_factory) as session:
        after = CuttingService(session).scarcity(request)
    assert after.status=='no_proof' and after.recommended_remnant_id is None
    assert after.inventory_version != before.inventory_version
