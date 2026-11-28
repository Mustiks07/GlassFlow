"""Disclosed real-HTTP P1 plus changed identities; no independent oracle access."""

import pytest

from glassflow.modules.intelligence.quality.dialogs import check_dialog

from .fakes import reply, tool_call
from .test_api import app_client as _app_client
from .test_post_p0 import turn
from .test_post_provenance import call, set_runtime

app_client = _app_client


@pytest.mark.parametrize("identifier", ["ZETA-POST-18484", "Q7Z8", "VX-9061-XR", "NOVABOLT732"])
def test_unknown_explicit_code_cannot_be_replaced_with_generic_hardware(app_client, identifier):
    result = turn(app_client, f"Сколько стоит неизвестное крепление {identifier}, модель и параметры неизвестны?")
    assert result["status"] == "manager_handoff" and result["quote"] is None
    assert result["card"]["catalog_product_id"] is None
    assert "400" not in result["answer"] and "200" not in result["answer"]


def test_exact_csv_unknown_request_remains_unpriced_in_batch(app_client):
    from .test_api import kb_version
    response = app_client.post("/api/v1/assistant/batch", json={
        "dataset_id": "ds-a", "kb_version": kb_version(app_client), "allow_ai": False,
        "questions": [{"id": "new-csv-id", "question": "Нужна цена неизвестного крепления ZETA-POST-18484, без известной модели."}],
    })
    assert response.status_code == 200
    answer = response.json()["answers"][0]
    assert answer["status"] == "manager_handoff"
    assert "400" not in answer["answer"] and "200" not in answer["answer"]


@pytest.mark.parametrize("text", [
    "Сколько стоит крепление бренда Новаболт?",
    "Сколько стоит крепление бренда Novaforge?",
    "Сколько стоит крепление Qorlix?",
    "Нужна фурнитура неизвестной марки, какое крепление подойдет?",
])
def test_unknown_brand_never_invents_a_catalogue_identity(app_client, text):
    result = turn(app_client, text)
    assert result["status"] in {"manager_handoff", "clarification"}
    assert result["quote"] is None and result["card"]["catalog_product_id"] is None


def test_generic_single_hardware_candidate_is_still_not_a_confirmed_choice(app_client):
    result = turn(app_client, "Сколько стоит крепление Космопульт?")
    assert result["status"] == "clarification" and result["quote"] is None
    assert result["card"]["catalog_product_id"] is None
    assert "не подтверждено" in result["answer"]


@pytest.mark.parametrize("code,product_id", [
    ("YZKJ-F2FTC", "sensor-dvoynoy-yzkj-f2ftc"),
    ("YZKJ-TCW", "sensor-odinarnyy-yzkj-tcw"),
])
def test_known_explicit_code_survives_unrelated_unknown_parameters(app_client, code, product_id):
    result = turn(app_client, f"Сколько стоит сенсорный переключатель {code}, прочие параметры неизвестны?")
    assert result["status"] == "answered" and result["card"]["catalog_product_id"] == product_id


def test_unknown_code_does_not_reuse_previous_product_or_leave_an_active_old_quote(app_client):
    first = turn(app_client, "Стекло 6 мм прозрачное 450×370 мм без обработки")
    result = turn(app_client, "Теперь неизвестное крепление U7X9, 3 шт.", conversation_id=first["conversation_id"])
    assert result["quote"] is None and result["card"]["catalog_product_id"] is None
    followup = turn(app_client, "А если 4 штуки?", conversation_id=first["conversation_id"])
    assert followup["quote"] is None and followup["card"]["catalog_product_id"] is None
    old = first["quote"]
    response = app_client.post(f"/api/v1/quotes/{old['quote_id']}/confirm", json={
        "dataset_id": "ds-a", "expected_revision": old["revision"], "confirmed_by": "Manager",
    })
    assert response.status_code == 409


def test_model_cannot_substitute_a_known_quote_for_an_unknown_requested_identity(app_client):
    set_runtime(app_client, [reply(tool_call("calculate_quote", {
        "catalog_product_id": "podves-skrytogo-krepleniya-zerkala", "quantity": 3})),
        reply(tool_call("submit_answer", {"answer_ru": "[[quote]]", "needs_manager": False}))])
    result = call(app_client, "Сколько стоит крепление NOMATCH-775, 3 шт.?", execution_mode="model_first").json()
    assert result["origin"] == "fallback" and result["quote"] is None
    assert result["model_call_count"] == 2 and result["verifier_reject_count"] == 1


def test_quality_cannot_whitelist_a_known_rate_for_an_unknown_customer_sku(kb):
    result = check_dialog(kb, "changed-id", "Сколько стоит неизвестное крепление NEWMODEL-77?",
                          "Подвес для скрытого крепления зеркала — 400 тг за штуку.")
    assert result.verdict == "NEEDS_REVIEW" and result.correct is None
    assert result.reason_code == "explicit_unknown_product"
