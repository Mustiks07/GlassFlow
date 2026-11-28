"""Synthetic measurement API regression data is never evidence of actual human labor."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from glassflow.core.models import AuditRow, ObjectRow
from glassflow.main import create_app
from glassflow.modules.platform import labor


@pytest.fixture()
def runtime(tmp_path):
    with TestClient(create_app(tmp_path, testing=True)) as client:
        client.get('/api/v1/session')
        source = post(client, '/datasets/demo')
        working = post(client, f"/datasets/{source['dataset_id']}/working-copy", {})
        yield client, source, working


def post(client, path, body=None, key=None):
    import time
    r = client.post('/api/v1' + path, json=body, headers={'Idempotency-Key': key or str(time.time_ns())})
    assert r.status_code in {200, 202}, r.text
    return r.json()


def study(client, d):
    return post(client, '/labor-studies', dict(dataset_id=d, name='API protocol regression',
        protocol='Synthetic automated test; not human evidence', observer='observer-A',
        start_definition='Task and inputs visible', end_definition='Result checked and saved'))


def start(client, s, pair='pair-1', method='manual', **changes):
    body = dict(dataset_id=s['dataset_id'], expected_version=s['version'], pair_id=pair,
        task_id=pair, task_input_ref='input:fixture', input_hash='a' * 64, operator='operator-A',
        method=method, planned_order='manual_first') | changes
    return post(client, f"/labor-studies/{s['study_id']}/measurements", body)


def action(client, s, operation, **changes):
    measurement = s['measurements'][-1]
    return post(client, f"/labor-studies/{s['study_id']}/measurements/{measurement['measurement_id']}/{operation}",
        dict(dataset_id=s['dataset_id'], expected_version=s['version'], operator='operator-A') | changes)


def test_elapsed_pause_active_attestation_and_real_pair_export(runtime, monkeypatch):
    client, _, working = runtime
    clock = [datetime(2026, 11, 28, 8, tzinfo=UTC)]
    monkeypatch.setattr(labor, 'moment', lambda: clock[0])
    s = study(client, working['dataset_id'])
    for number in range(10):
        s = start(client, s, f'task-{number}')
        clock[0] += timedelta(seconds=4)
        s = action(client, s, 'pause')
        clock[0] += timedelta(seconds=6)
        s = action(client, s, 'resume')
        clock[0] += timedelta(seconds=6)
        s = action(client, s, 'finish', result_ref=f'manual-result:{number}', error_count=1, rework_seconds='2')
        m = s['measurements'][-1]
        assert m['elapsed_seconds'] == '16.000' and m['recorded_running_seconds'] == '10.000'
        assert m['attested_active_seconds'] is None and not m['human_confirmed']
        s = action(client, s, 'attest', active_seconds='10', human_confirmed=True)
        s = start(client, s, f'task-{number}', 'app')
        clock[0] += timedelta(seconds=14)
        s = action(client, s, 'finish', result_ref=f'app-result:{number}', rework_seconds='3')
        s = action(client, s, 'attest', active_seconds='12', human_confirmed=True)
        clock[0] += timedelta(seconds=1)
    assert s['export_ready'] and s['ready_pair_count'] == 10
    result = client.get(f"/api/v1/labor-studies/{s['study_id']}/export", params={'dataset_id': s['dataset_id']})
    assert result.status_code == 200, result.text
    exported = result.json()
    assert exported['negative_saving_pairs'] == 10 and exported['median_saved_active_seconds'] == '-2.000'
    assert len(exported['labor_studies']) == 10 and exported['measurement_status'] == 'supplied_measurements'
    # Existing U07 canonical DTO accepts the export without rewriting numbers.
    from glassflow.contracts.economics import LaborStudy
    assert LaborStudy.model_validate(exported['labor_studies'][0]).manual_active_seconds == '10'
    assert [e['action'] for e in s['measurements'][0]['events']] == ['start', 'pause', 'resume', 'finish', 'attest']


def test_mismatch_overlap_no_zero_time_or_automatic_human_claim(runtime, monkeypatch):
    client, source, working = runtime
    clock = [datetime(2026, 11, 28, 8, tzinfo=UTC)]
    monkeypatch.setattr(labor, 'moment', lambda: clock[0])
    s = study(client, working['dataset_id'])
    s = start(client, s)
    path = f"/api/v1/labor-studies/{s['study_id']}/measurements"
    body = dict(dataset_id=s['dataset_id'], expected_version=s['version'], pair_id='pair-1', task_id='pair-1',
        task_input_ref='input:fixture', input_hash='b' * 64, operator='operator-A', method='app', planned_order='manual_first')
    r = client.post(path, json=body, headers={'Idempotency-Key':'mismatch'})
    assert r.status_code == 409 and r.json()['code'] == 'PAIR_INPUT_MISMATCH'
    body['input_hash'] = 'a' * 64
    r = client.post(path, json=body, headers={'Idempotency-Key':'overlap'})
    assert r.status_code == 409 and r.json()['code'] == 'PAIR_OVERLAP'
    assert client.get(f"/api/v1/labor-studies/{s['study_id']}/export", params={'dataset_id':s['dataset_id']}).status_code == 409
    mid = s['measurements'][-1]['measurement_id']
    r = client.post(f"{path}/{mid}/attest", json=dict(dataset_id=s['dataset_id'], expected_version=s['version'],
        operator='operator-A', active_seconds='2', human_confirmed=True), headers={'Idempotency-Key':'early'})
    assert r.status_code == 409
    r = client.post('/api/v1/labor-studies', json=dict(dataset_id=source['dataset_id'], name='Invalid',
        protocol='p',observer='o',start_definition='s',end_definition='e'),headers={'Idempotency-Key':'immutable'})
    assert r.status_code == 409


def test_restart_is_visible_requires_explicit_ack_and_durable_immutable_attestation(runtime, monkeypatch):
    client, _, working = runtime
    clock = [datetime(2026, 11, 28, 8, tzinfo=UTC)]
    monkeypatch.setattr(labor, 'moment', lambda: clock[0])
    s = start(client, study(client, working['dataset_id']))
    monkeypatch.setattr(labor, 'PROCESS_EPOCH', 'new-python-process-test')
    clock[0] += timedelta(seconds=20)
    r = client.get(f"/api/v1/labor-studies/{s['study_id']}", params={'dataset_id':s['dataset_id']}).json()
    assert r['measurements'][-1]['interruption_detected'] and not r['measurements'][-1]['human_confirmed']
    mid = s['measurements'][-1]['measurement_id']
    path = f"/api/v1/labor-studies/{s['study_id']}/measurements/{mid}/finish"
    body = dict(dataset_id=s['dataset_id'], expected_version=s['version'], operator='operator-A', result_ref='real-result-ref')
    response = client.post(path,json=body,headers={'Idempotency-Key':'no-ack'})
    assert response.status_code == 409 and response.json()['code'] == 'INTERRUPTION_ACK_REQUIRED'
    s = post(client,path.removeprefix('/api/v1'),body | {'acknowledge_interruption':True,'note':'Operator reviewed interrupted interval'})
    s = action(client,s,'attest',active_seconds='18',human_confirmed=True)
    assert s['measurements'][-1]['interruption_acknowledged']
    r = client.post(path,json=body | {'expected_version':s['version']},headers={'Idempotency-Key':'immutable'})
    assert r.status_code == 409 and r.json()['code'] == 'MEASUREMENT_IMMUTABLE'


def test_workflow_actual_order_source_change_projection_does_not_write_state(runtime):
    client, _, working = runtime
    d=working['dataset_id']
    s=post(client,'/order-sheets',dict(dataset_id=d,customer_ref='C-test',request_text='Glass actual test'))
    queue=client.get('/api/v1/workflow/queue',params={'dataset_id':d}).json()
    assert queue['items'][0]['reason_code']=='ORDER_QUOTE_REQUIRED'
    q=post(client,'/quotes',dict(dataset_id=d,customer_id='C-test',catalog_product_id='steklo-6-prozrachnoe',
        kb_version=working['kb_version'],dimensions=dict(length_mm=450,width_mm=370),quantity=1,
        processing=dict(kind='euro_edge',sides='all'),inventory_mode='free_whole_remnants'))
    q=post(client,f"/quotes/{q['quote_id']}/confirm",dict(dataset_id=d,expected_revision=1,confirmed_by='manager'))
    rid=q['candidate_refs'][0]['remnant_id']
    s=post(client,f"/order-sheets/{s['order_id']}/bind",dict(dataset_id=d,expected_version=s['version'],operator='manager',
        quote_id=q['quote_id'],quote_revision=1,remnant_id=rid,remnant_version=0))
    factory=client.app.state.session_factory
    with factory() as session:
        audit_count=session.scalar(select(func.count()).select_from(AuditRow))
        order_version=session.get(ObjectRow,(d,'order_sheet',s['order_id'])).version
    queue=client.get('/api/v1/workflow/queue',params={'dataset_id':d}).json()
    assert queue['items'][0]['reason_code']=='QUOTE_CONFIRM_REQUIRED'
    r=client.patch(f'/api/v1/remnants/{rid}/measurement',json=dict(dataset_id=d,expected_version=0,
        dimensions=dict(length_mm=461,width_mm=380),reason='Actual changed dimensions'))
    assert r.status_code==200,r.text
    with factory() as session:
        audit_count=session.scalar(select(func.count()).select_from(AuditRow))
    queue=client.get('/api/v1/workflow/queue',params={'dataset_id':d}).json()
    assert queue['items'][0]['reason_code']=='ORDER_SOURCE_CHANGED'
    assert queue['items'][0]['amount_tg'] is None and queue['projection_only']
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AuditRow))==audit_count
        assert session.get(ObjectRow,(d,'order_sheet',s['order_id'])).version==order_version
