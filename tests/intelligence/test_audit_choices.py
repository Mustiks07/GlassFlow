from .test_audit_numeric_boundaries import client as real_client

client = real_client


def test_price_basis_button_preserves_three_sheets(client, imported):
    first = client.post('/api/v1/assistant/turns', json=dict(dataset_id=imported['dataset_id'],
        kb_version=imported['kb_version'], allow_ai=False, inventory_mode='none',
        text='Сколько стоят три штуки рифлёного прозрачного стекла 8 мм?')).json()
    choice = next(o for o in first['clarification_options'] if o['label'] == 'Цена за целый лист')
    result = client.post('/api/v1/assistant/choices', json=dict(dataset_id=imported['dataset_id'],
        kb_version=imported['kb_version'], conversation_id=first['conversation_id'],
        turn_index=first['turn_index'], choice_id=choice['choice_id']))
    assert result.status_code == 200, result.text
    assert result.json()['quote']['quantity'] == 3
    assert result.json()['quote']['total_tg'] == '510000.00'


def test_unit_button_is_bound_to_conversation_and_does_not_confirm(client, imported):
    first = client.post('/api/v1/assistant/turns', json=dict(dataset_id=imported['dataset_id'],
        kb_version=imported['kb_version'], allow_ai=False, inventory_mode='none',
        text='Стекло 6 мм прозрачное 45,0x37,0, 2 штуки, евро-кромка по всем сторонам')).json()
    assert first['status'] == 'clarification' and first['quote'] is None
    options = first['clarification_options']
    choice = next(o for o in options if o['label'] == 'Сантиметры')
    body = dict(dataset_id=imported['dataset_id'], kb_version=imported['kb_version'],
        conversation_id=first['conversation_id'], turn_index=first['turn_index'], choice_id=choice['choice_id'])
    current = client.post('/api/v1/assistant/choices', json=body)
    assert current.status_code == 200, current.text
    quote = current.json()['quote']
    assert quote['total_tg'] == '3976.00' and quote['status'] == 'calculated'
    assert client.post('/api/v1/assistant/choices', json=body).status_code == 409
    history = client.get(f"/api/v1/assistant/conversations/{first['conversation_id']}", params={'dataset_id': imported['dataset_id']})
    assert history.status_code == 200


def test_sides_button_uses_existing_geometry(client, imported):
    first = client.post('/api/v1/assistant/turns', json=dict(dataset_id=imported['dataset_id'],
        kb_version=imported['kb_version'], allow_ai=False, inventory_mode='none',
        text='Стекло 6 мм прозрачное 450x370 мм, 2 штуки с евро-кромкой')).json()
    choice = next(o for o in first['clarification_options'] if o['label'] == 'Все четыре стороны')
    result = client.post('/api/v1/assistant/choices', json=dict(dataset_id=imported['dataset_id'],
        kb_version=imported['kb_version'], conversation_id=first['conversation_id'], turn_index=first['turn_index'], choice_id=choice['choice_id']))
    assert result.status_code == 200, result.text
    assert result.json()['quote']['total_tg'] == '3976.00'


def test_product_choice_does_not_erase_invalid_quantity(client, imported):
    first = client.post('/api/v1/assistant/turns', json=dict(dataset_id=imported['dataset_id'],
        kb_version=imported['kb_version'], allow_ai=False, inventory_mode='none',
        text='Рифлёное стекло 450x370 мм, 0 штук')).json()
    choice = next(o for o in first['clarification_options'] if o['kind'] == 'product')
    result = client.post('/api/v1/assistant/choices', json=dict(dataset_id=imported['dataset_id'],
        kb_version=imported['kb_version'], conversation_id=first['conversation_id'], turn_index=first['turn_index'], choice_id=choice['choice_id']))
    assert result.status_code == 200
    assert result.json()['status'] == 'clarification' and result.json()['quote'] is None
    assert 'quantity' in result.json()['card']['missing_parameters']
