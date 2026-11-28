"""Mock provider regression of source binding; never counted as live accuracy."""

import pytest

from .fakes import reply, tool_call
from .test_api import app_client as real_client
from .test_post_provenance import call, set_runtime

app_client = real_client


@pytest.mark.parametrize('changes', [{'length_mm': 45}, {'quantity': 1}])
def test_valid_tool_arithmetic_cannot_override_user_numbers(app_client, changes):
    args = dict(catalog_product_id='steklo-6-prozrachnoe', length_mm=450, width_mm=370,
                quantity=2, processing='euro_edge', sides='all') | changes
    set_runtime(app_client, [reply(tool_call('calculate_quote', args)), reply(tool_call('submit_answer', {
        'answer_ru': '[[quote]] Предварительную стоимость подтверждает менеджер.', 'needs_manager': False}))])
    result = call(app_client, 'Стекло 6 мм прозрачное 45 см x 370 мм, 2 штуки, евро-кромка по всем сторонам.', execution_mode='model_first').json()
    assert result['origin'] == 'fallback' and result['verifier_reject_count'] == 1
    assert result['quote']['quantity'] == 2
    assert result['quote']['dimensions'] == dict(length_mm=450, width_mm=370)
    assert result['quote']['total_tg'] == '3976.00'
