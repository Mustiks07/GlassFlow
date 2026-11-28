"""Two disclosed post-integration defects; no independent examiner data is loaded."""

from .test_api import app_client as _app_client
from .test_api import kb_version

app_client = _app_client


def turn(client, text, **extra):
    response = client.post("/api/v1/assistant/turns", json={
        "dataset_id": "ds-a", "kb_version": kb_version(client), "text": text,
        "allow_ai": False, "inventory_mode": "none", **extra,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_unknown_selected_edges_cannot_create_confirmable_glass_only_quote(app_client):
    reply = turn(app_client, "Стекло 6 мм прозрачное 640×420 мм, 4 шт., кромка по выбранным сторонам. Рассчитайте итог.")
    assert reply["status"] == "clarification" and "edge_sides" in reply["card"]["missing_parameters"]
    assert reply["quote"] is None
    resolved = turn(app_client, "По всем четырем сторонам", conversation_id=reply["conversation_id"])
    quote = resolved["quote"]
    assert quote["total_tg"] == "11993.60"
    assert quote["processing"]["kind"] == "euro_edge"
    assert quote["origin"] == "assistant_deterministic"
    assert quote["origin_conversation_id"] == reply["conversation_id"]
    confirmed = app_client.post(f"/api/v1/quotes/{quote['quote_id']}/confirm", json={
        "dataset_id": "ds-a", "expected_revision": quote["revision"], "confirmed_by": "manager",
    })
    assert confirmed.status_code == 200


def test_incomplete_followup_retires_previous_quote(app_client):
    reply = turn(app_client, "Стекло 6 мм прозрачное 640×420 мм, 4 шт., кромка по всем четырем сторонам")
    quote = reply["quote"]
    followup = turn(app_client, "Кромка по выбранным сторонам", conversation_id=reply["conversation_id"])
    assert followup["quote"] is None
    response = app_client.post(f"/api/v1/quotes/{quote['quote_id']}/confirm", json={
        "dataset_id": "ds-a", "expected_revision": quote["revision"], "confirmed_by": "manager",
    })
    assert response.status_code == 409


def test_generic_sensor_does_not_choose_sku_and_explicit_sku_resolves(app_client):
    generic = turn(app_client, "Нужен сенсорный переключатель для зеркала, сколько за 3 шт?")
    assert generic["status"] == "clarification"
    assert generic["card"]["catalog_product_id"] is None
    assert generic["quote"] is None
    assert len(generic["card"]["alternatives"]) >= 2
    chosen = turn(app_client, "Нужен YZKJ-F2FTC, 3 шт.", conversation_id=generic["conversation_id"])
    assert chosen["card"]["catalog_product_id"] == "sensor-dvoynoy-yzkj-f2ftc"
    assert chosen["status"] == "answered"
