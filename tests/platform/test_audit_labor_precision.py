"""Synthetic boundary checks only; these are not genuine human labor evidence."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from test_post_labor_workflow import action, post, start, study

from glassflow.contracts.economics import LaborStudy
from glassflow.core.models import ObjectRow
from glassflow.modules.platform import labor


@pytest.mark.parametrize('micros', [400, 500, 600, 999600])
def test_accepted_ten_pairs_always_export(client, imported, monkeypatch, micros):
    d = post(client, f"/datasets/{imported['dataset_id']}/working-copy", {})['dataset_id']
    clock = [datetime(2026, 11, 28, 10, tzinfo=UTC)]
    monkeypatch.setattr(labor, 'moment', lambda: clock[0])
    s = study(client, d)
    for n in range(10):
        methods = ['manual', 'app'] if n % 2 == 0 else ['app', 'manual']
        for method in methods:
            s = start(client, s, f'task-{n}', method, planned_order=methods[0] + '_first')
            clock[0] += timedelta(seconds=10, microseconds=micros)
            s = action(client, s, 'finish', result_ref=f'synthetic-{n}-{method}')
            shown = s['measurements'][-1]['elapsed_seconds']
            s = action(client, s, 'attest', active_seconds=shown, human_confirmed=True)
            clock[0] += timedelta(seconds=1)
    assert s['export_ready'] and s['ready_pair_count'] == 10
    response = client.get(f"/api/v1/labor-studies/{s['study_id']}/export", params={'dataset_id': d})
    assert response.status_code == 200, response.text
    assert len(response.json()['labor_studies']) == 10
    for row in response.json()['labor_studies']:
        LaborStudy.model_validate(row)


def test_legacy_bad_attestation_requires_explicit_review(client, imported, monkeypatch):
    d = post(client, f"/datasets/{imported['dataset_id']}/working-copy", {})['dataset_id']
    clock = [datetime(2026, 11, 28, 10, tzinfo=UTC)]
    monkeypatch.setattr(labor, 'moment', lambda: clock[0])
    s = start(client, study(client, d))
    clock[0] += timedelta(seconds=10, microseconds=999600)
    s = action(client, s, 'finish', result_ref='synthetic-result')
    mid = s['measurements'][-1]['measurement_id']
    base = f"/api/v1/labor-studies/{s['study_id']}/measurements/{mid}"
    body = dict(dataset_id=d, expected_version=s['version'], operator='operator-A', active_seconds='11.000', human_confirmed=True)
    assert client.post(base + '/attest', json=body, headers={'Idempotency-Key': 'bad-active'}).status_code == 409
    # Simulate a previously persisted c6b4b02 attestation, not a new valid entry.
    with client.app.state.session_factory.begin() as session:
        row = session.get(ObjectRow, (d, 'labor_study', s['study_id']))
        data = deepcopy(row.data)
        data['measurements'][-1].update(state='attested', attested_active_seconds='11.000', human_confirmed=True, attested_by='operator-A')
        row.data = data
        old_events = deepcopy(data['measurements'][-1]['events'])
    s = client.get(f"/api/v1/labor-studies/{s['study_id']}", params={'dataset_id': d}).json()
    assert not s['export_ready'] and s['measurements'][-1]['requires_attestation_review']
    assert client.post(base + '/reopen', json=body).status_code == 422
    recovery = {k: v for k, v in body.items() if k != 'active_seconds'}
    s = post(client, base.removeprefix('/api/v1') + '/reopen', recovery | {'note': 'Human reviewed old rounded interval'})
    m = s['measurements'][-1]
    assert m['state'] == 'finished' and not m['human_confirmed']
    assert m['events'][:-1] == old_events
    assert m['events'][-1]['details']['previous_attestation']['attested_active_seconds'] == '11.000'
    s = action(client, s, 'attest', active_seconds='10.999600', human_confirmed=True)
    assert not s['measurements'][-1]['requires_attestation_review']
