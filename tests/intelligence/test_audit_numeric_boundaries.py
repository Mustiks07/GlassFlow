"""New counterexamples from the c6b4b02 audit, exercised through real persistence."""

import pytest
from fastapi.testclient import TestClient

from glassflow.main import create_app
from glassflow.modules.intelligence.nlu.extract import extract


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, testing=True)) as value:
        value.get('/api/v1/session')
        yield value


@pytest.mark.parametrize("dimensions", [
    "45 см x 370 мм", "450 мм x 37 см", "0,45 м × 370 мм", "450 мм на 0,37 м",
    "45 x 37 см", "ширина 370 мм, длина 450 мм", "длина: 45 см, ширина: 370 мм",
])
def test_equivalent_dimensions_have_same_persisted_quote(client, imported, dimensions):
    response = client.post('/api/v1/assistant/turns', json={
        'dataset_id': imported['dataset_id'], 'kb_version': imported['kb_version'],
        'text': f'Стекло 6 мм прозрачное {dimensions}, 2 штуки, евро-кромка по всем сторонам. Рассчитайте итог.',
        'allow_ai': False, 'inventory_mode': 'none',
    })
    assert response.status_code == 200, response.text
    q = response.json()['quote']
    assert q['dimensions'] == dict(length_mm=450, width_mm=370)
    assert q['quantity'] == 2 and q['total_tg'] == '3976.00'
    saved = client.get(f"/api/v1/quotes/{q['quote_id']}", params={'dataset_id': imported['dataset_id']})
    assert saved.status_code == 200 and saved.json()['total_tg'] == q['total_tg']


@pytest.mark.parametrize('invalid', ['0 штук', '-2 штуки', '−2 штуки', '1,5 штуки', '1.5 штуки',
    'ноль штук', 'минус две штуки', '1/2 штуки', 'количество: 0', 'количество: ноль', 'количество: 1,5'])
def test_invalid_count_never_becomes_confirmable_quote(client, imported, invalid):
    body = dict(dataset_id=imported['dataset_id'], kb_version=imported['kb_version'], allow_ai=False,
                text=f'Стекло 6 мм прозрачное 450x370 мм, {invalid}, евро-кромка по всем сторонам.')
    result = client.post('/api/v1/assistant/turns', json=body)
    assert result.status_code == 200
    assert result.json()['status'] == 'clarification'
    assert result.json()['quote'] is None
    proposal = extract(body['text'])
    assert proposal.invalid_quantity and proposal.quantity is None


def test_invalid_followup_retires_previous_draft(client, imported):
    body = dict(dataset_id=imported['dataset_id'], kb_version=imported['kb_version'], allow_ai=False,
                text='Стекло 6 мм прозрачное 450x370 мм, 2 штуки, без кромки')
    previous = client.post('/api/v1/assistant/turns', json=body).json()
    current = client.post('/api/v1/assistant/turns', json=body | {
        'conversation_id': previous['conversation_id'], 'text': 'Количество: -2 штуки',
    }).json()
    assert current['quote'] is None and current['status'] == 'clarification'
    quote = previous['quote']
    result = client.post(f"/api/v1/quotes/{quote['quote_id']}/confirm", json={
        'dataset_id': imported['dataset_id'], 'expected_revision': quote['revision'], 'confirmed_by': 'audit',
    }, headers={'Idempotency-Key': 'invalid-followup-confirm'})
    assert result.status_code == 409, result.text


@pytest.mark.parametrize('raw', ['-450x370 мм', '450x-370 мм', '−450×370 мм', 'минус 450x370 мм'])
def test_negative_geometry_is_not_reinterpreted(raw):
    ex = extract(raw)
    assert not ex.dimensions and ex.invalid_dimensions


def test_dash_separator_is_not_a_negative_size():
    ex = extract('Размер — 450x370 мм')
    assert ex.dimensions[0].length_mm == 450 and not ex.invalid_dimensions


def test_grouped_numbers_do_not_lose_sign_or_leading_digits():
    valid = extract('1 250 мм x 37 см, 1 500 штук')
    assert valid.dimensions[0].length_mm == 1250 and valid.dimensions[0].width_mm == 370
    assert valid.quantity == 1500
    invalid = extract('-1 250 x 3 700 мм, -1 500 штук')
    assert invalid.invalid_dimensions and not invalid.dimensions
    assert invalid.invalid_quantity and invalid.quantity is None


def test_multiple_sheets_compute_total(engine):
    result = engine.respond('Нужно 3 листа рифлёного прозрачного стекла 8 мм. Сколько всего?')
    assert result.pricing is not None and str(result.pricing.total) == '510000.00'
    assert not result.needs_manager
