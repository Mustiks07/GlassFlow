"""Real C2/import/SQLite/PDF route; controlled labor is synthetic regression data only."""

import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from test_post_labor_workflow import action, post, start, study

from glassflow.main import create_app
from glassflow.modules.platform import labor


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, testing=True)) as c:
        c.get('/api/v1/session')
        yield c


def test_real_wizard_first_scenario_without_json_or_manual_ids(client, imported, monkeypatch):
    d = post(client, f"/datasets/{imported['dataset_id']}/working-copy", {})['dataset_id']
    job = post(client, '/cutting/solve', dict(dataset_id=d, config=dict(profile='quick', time_limit_seconds=3)))
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/jobs/{job['job_id']}").json()
        if job['state'] in {'completed', 'failed'}:
            break
        time.sleep(.1)
    assert job['state'] == 'completed', job
    plan = job['result']
    placed = next(p for p in plan['placements'] if p['remnant_id'] != 'NEW')
    draft = post(client, f"/plans/{plan['plan_id']}/draft", dict(dataset_id=d, base_revision=plan['revision'],
        edits=[dict(part_id=placed['part_id'], action='unplace')]))
    assert draft['validation']['valid']
    checked = client.post(f"/api/v1/plans/{plan['plan_id']}/validate", params={'dataset_id': d, 'revision': draft['plan']['revision']})
    assert checked.status_code == 200 and checked.json()['valid']
    choices = client.get('/api/v1/economics/scenarios/sources', params={'dataset_id': d})
    assert choices.status_code == 200, choices.text
    rows = choices.json()['results']
    assert len(rows) >= 2 and rows[0]['comparison_key'] == rows[1]['comparison_key']
    high, low = sorted(rows, key=lambda r: float(r['material_value_tg']), reverse=True)[:2]
    clock = [datetime(2026, 11, 28, 10, tzinfo=UTC)]
    monkeypatch.setattr(labor, 'moment', lambda: clock[0])
    s = study(client, d)
    for n in range(10):
        order = ['manual', 'app'] if n % 2 == 0 else ['app', 'manual']
        for method in order:
            s = start(client, s, f'task-{n}', method, planned_order=order[0] + '_first')
            clock[0] += timedelta(seconds=10 if method == 'manual' else 20)
            s = action(client, s, 'finish', result_ref=f'synthetic-result-{n}-{method}')
            s = action(client, s, 'attest', active_seconds=s['measurements'][-1]['elapsed_seconds'], human_confirmed=True)
    assumptions = dict(monthly_operations='100', monthly_dataset_multiplier='1', hourly_rate_tg='3600',
        hourly_rate_basis='Synthetic rate', monthly_volume_basis='Synthetic volume', ai_monthly_tg='0',
        ai_cost_basis='Synthetic offline regression', hosting_monthly_tg='100', support_monthly_tg='100',
        implementation_tg='1000', implementation_basis='Synthetic implementation', material_use_fraction='1', material_use_basis='Synthetic scenario')
    body = dict(dataset_id=d, name='SYNTHETIC API wizard check', baseline_ref=high['reference'], final_ref=low['reference'],
        study_id=s['study_id'], study_version=s['version'], assumptions=assumptions)
    result = post(client, '/economics/scenarios/wizard', body, key='wizard-first')
    assert float(result['results']['scenario_net_effect_tg']) < 0 and result['results']['payback_months'] is None
    assert result['inputs']['labor_studies'] and result['inputs']['final_material_value_tg'] == low['material_value_tg']
    again = post(client, '/economics/scenarios/wizard', body, key='wizard-first')
    assert result == again
    saved = client.get('/api/v1/economics/scenarios', params={'dataset_id': d}).json()
    assert [r['scenario_id'] for r in saved] == [result['scenario_id']]
    pdf = client.get(f"/api/v1/economics/scenarios/{result['scenario_id']}/pdf", params={'dataset_id': d, 'version': 0})
    assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF')
    bad = client.post('/api/v1/economics/scenarios/wizard', json=body | {'final_ref': high['reference']}, headers={'Idempotency-Key': 'same-result'})
    assert bad.status_code == 409
