"""HTTP contract tests on the real FastAPI app and SQLite (no fixtures in release code)."""

import csv
import io
import json
import random

import pytest
from fastapi.testclient import TestClient

from glassflow.main import create_app
from glassflow.modules.intelligence.service import IntelligenceService
from glassflow.modules.intelligence.sources import InMemorySources

from .conftest import KB_PATH, MATERIALS_PATH, PACK


@pytest.fixture()
def app_client(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        sources = InMemorySources()
        sources.add_kb("ds-a", KB_PATH.read_bytes())
        sources.set_materials("ds-a", MATERIALS_PATH.read_bytes())
        app.state.intelligence_service = IntelligenceService(sources, app.state.session_factory)
        client.sources = sources
        yield client


def kb_version(client, dataset="ds-a"):
    return next(v["kb_version"] for v in client.get("/api/v1/catalog/versions", params={"dataset_id": dataset}).json() if v["current"])


def quote_body(client, dataset="ds-a", **kwargs):
    body = {
        "dataset_id": dataset,
        "catalog_product_id": "steklo-6-prozrachnoe",
        "dimensions": {"length_mm": 450, "width_mm": 370},
        "quantity": 1,
        "processing": {"kind": "euro_edge", "sides": "all"},
        "kb_version": kb_version(client, dataset),
    }
    body.update(kwargs)
    return body


def modified_kb(rate: int) -> bytes:
    document = json.loads(KB_PATH.read_text(encoding="utf-8"))
    for item in document["товары"]:
        if item["id"] == "steklo-6-prozrachnoe":
            item["цена_за_м2_тг"] = rate
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


def test_quote_contract_matches_tz_example(app_client):
    response = app_client.post("/api/v1/quotes/calculate", json=quote_body(app_client))
    assert response.status_code == 200
    quote = response.json()
    assert quote["total_tg"] == "1988.00" and quote["preliminary"] is True
    assert [c["amount_tg"] for c in quote["components"]] == ["1332.00", "656.00"]
    assert quote["material_mapping_status"] == "confirmed" and quote["material_id"] == "clear-6"
    assert quote["rounding_policy"].startswith("ROUND_HALF_UP")
    assert quote["source_versions"]["kb"] == quote["kb_version"]
    assert all(isinstance(c["amount_tg"], str) for c in quote["components"])


def test_t21_new_price_after_confirmation_creates_revision(app_client):
    created = app_client.post("/api/v1/quotes", json=quote_body(app_client)).json()
    quote_id = created["quote_id"]
    confirmed = app_client.post(
        f"/api/v1/quotes/{quote_id}/confirm", json={"dataset_id": "ds-a", "expected_revision": 1, "confirmed_by": "M1"},
        headers={"Idempotency-Key": "k-1"},
    )
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"
    app_client.sources.add_kb("ds-a", modified_kb(9000), origin="working_copy_price_change")
    stale = app_client.get(f"/api/v1/quotes/{quote_id}", params={"dataset_id": "ds-a"}).json()
    assert stale["stale"] is True and stale["total_tg"] == "1988.00"
    revised = app_client.post(
        f"/api/v1/quotes/{quote_id}/revise", json={"dataset_id": "ds-a", "expected_revision": 1, "reprice_current_kb": True}
    )
    assert revised.status_code == 200
    body = revised.json()
    assert body["revision"] == 2 and body["total_tg"] == "2154.50"  # 0.1665 × 9000 = 1498.50 + 656
    assert body["diff"]["changed_fields"] == ["kb_version"]
    assert body["diff"]["total_before_tg"] == "1988.00"
    first = app_client.get(f"/api/v1/quotes/{quote_id}", params={"dataset_id": "ds-a", "revision": 1}).json()
    assert first["status"] == "confirmed" and first["total_tg"] == "1988.00"
    history = app_client.get(f"/api/v1/quotes/{quote_id}/revisions", params={"dataset_id": "ds-a"}).json()
    assert [(q["revision"], q["status"]) for q in history] == [(1, "confirmed"), (2, "calculated")]


def test_confirm_idempotency_and_conflicts(app_client):
    quote_id = app_client.post("/api/v1/quotes", json=quote_body(app_client)).json()["quote_id"]
    body = {"dataset_id": "ds-a", "expected_revision": 1, "confirmed_by": "M1"}
    first = app_client.post(f"/api/v1/quotes/{quote_id}/confirm", json=body, headers={"Idempotency-Key": "a"})
    again = app_client.post(f"/api/v1/quotes/{quote_id}/confirm", json=body, headers={"Idempotency-Key": "a"})
    assert first.json() == again.json()
    other = app_client.post(f"/api/v1/quotes/{quote_id}/confirm", json={**body, "confirmed_by": "M2"}, headers={"Idempotency-Key": "a"})
    assert other.status_code == 409 and other.json()["code"] == "ALREADY_CONFIRMED"
    wrong_revision = app_client.post(f"/api/v1/quotes/{quote_id}/revise", json={"dataset_id": "ds-a", "expected_revision": 7})
    assert wrong_revision.status_code == 409 and wrong_revision.json()["conflict_objects"]


def test_incomplete_quote_cannot_be_confirmed(app_client):
    body = quote_body(app_client, catalog_product_id="riflenoe-prozrachnoe-8", processing={"kind": "none"})
    quote = app_client.post("/api/v1/quotes", json=body).json()
    assert quote["status"] == "needs_review" and quote["total_tg"] is None
    assert quote["material_mapping_status"] == "unmapped"
    assert quote["unknown_components"][0]["reason_code"] == "per_m2_price_not_in_kb"
    response = app_client.post(f"/api/v1/quotes/{quote['quote_id']}/confirm", json={"dataset_id": "ds-a", "expected_revision": 1, "confirmed_by": "M1"})
    assert response.status_code == 409


def test_t04_datasets_with_same_ids_are_isolated(app_client):
    app_client.sources.add_kb("ds-b", modified_kb(1000))
    app_client.sources.set_materials("ds-b", MATERIALS_PATH.read_bytes())
    a = app_client.post("/api/v1/quotes", json=quote_body(app_client, "ds-a")).json()
    b = app_client.post("/api/v1/quotes", json=quote_body(app_client, "ds-b")).json()
    assert (a["total_tg"], b["total_tg"]) == ("1988.00", "822.50")
    cross = app_client.get(f"/api/v1/quotes/{a['quote_id']}", params={"dataset_id": "ds-b"})
    assert cross.status_code == 404
    stale = app_client.post("/api/v1/quotes", json={**quote_body(app_client, "ds-b"), "kb_version": kb_version(app_client, "ds-a")})
    assert stale.status_code == 409 and stale.json()["code"] == "STALE_KB_VERSION"


def test_mapping_confirmation_is_versioned(app_client):
    mappings = {m["catalog_product_id"]: m for m in app_client.get("/api/v1/catalog/mappings", params={"dataset_id": "ds-a"}).json()}
    mirror = mappings["zerkalo-4-list-2750"]
    assert mirror["status"] == "proposed" and mirror["material_id"] is None
    ok = app_client.post(
        "/api/v1/catalog/mappings/zerkalo-4-list-2750/confirm",
        json={"dataset_id": "ds-a", "material_id": "mirror-4", "expected_version": 0, "confirmed_by": "M2"},
    )
    assert ok.status_code == 200 and ok.json()["status"] == "confirmed" and ok.json()["version"] == 1
    conflict = app_client.post(
        "/api/v1/catalog/mappings/zerkalo-4-list-2750/confirm",
        json={"dataset_id": "ds-a", "material_id": "mirror-4", "expected_version": 0, "confirmed_by": "M2"},
    )
    assert conflict.status_code == 409
    bad = app_client.post(
        "/api/v1/catalog/mappings/riflenoe-prozrachnoe-8/confirm",
        json={"dataset_id": "ds-a", "material_id": "no-such", "expected_version": 0, "confirmed_by": "M2"},
    )
    assert bad.status_code == 422


def test_assistant_conversation_keeps_context_and_customer_switch_resets(app_client):
    version = kb_version(app_client)
    first = app_client.post("/api/v1/assistant/turns", json={"dataset_id": "ds-a", "kb_version": version, "customer_id": "C1",
                                                             "text": "Стекло прозрачное 6 мм 450×370 с евро-кромкой по четырем сторонам"}).json()
    assert first["quote"]["total_tg"] == "1988.00" and first["mode"] == "local_limited"
    assert first["card"]["confirmed_parameters"]["length_mm"] == "450"
    cid = first["conversation_id"]
    second = app_client.post("/api/v1/assistant/turns", json={"dataset_id": "ds-a", "kb_version": version, "customer_id": "C1",
                                                              "conversation_id": cid, "text": "а если 451×370?"}).json()
    assert second["quote"]["total_tg"] == "1991.76" and second["quote"]["revision"] == 2
    assert second["quote"]["quote_id"] == first["quote"]["quote_id"]
    other = app_client.post("/api/v1/assistant/turns", json={"dataset_id": "ds-a", "kb_version": version, "customer_id": "C2",
                                                             "conversation_id": cid, "text": "а две штуки?"}).json()
    assert other["quote"] is None
    assert any("Клиент изменен" in note for note in other["card"]["assumptions"])
    conversation = app_client.get(f"/api/v1/assistant/conversations/{cid}", params={"dataset_id": "ds-a"}).json()
    assert len(conversation["turns"]) == 3


def _rows(path):
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))


def test_t31_id_permutation_and_rephrase_follow_content(app_client):
    version = kb_version(app_client)
    rows = _rows(PACK / "2_assistant_crm" / "questions_open.csv")
    baseline = app_client.post("/api/v1/assistant/batch", json={"dataset_id": "ds-a", "kb_version": version,
                                                                "questions": [{"id": r["id"], "question": r["question"]} for r in rows]}).json()
    by_text = {r["question"]: a["answer"] for r, a in zip(rows, baseline["answers"])}
    shuffled = rows[:]
    random.Random(7).shuffle(shuffled)
    renamed = [{"id": f"Z{index:03d}", "question": r["question"]} for index, r in enumerate(shuffled)]
    result = app_client.post("/api/v1/assistant/batch", json={"dataset_id": "ds-a", "kb_version": version, "questions": renamed}).json()
    assert result["complete"] is True
    for row, answer in zip(renamed, result["answers"]):
        assert answer["id"] == row["id"]
        assert answer["answer"] == by_text[row["question"]]
    swapped = app_client.post("/api/v1/assistant/batch", json={"dataset_id": "ds-a", "kb_version": version, "questions": [
        {"id": "Q15", "question": "Сколько стоит Стекло серое за квадратный метр?"},
        {"id": "Q17", "question": "Сколько стоит Стекло 4 мм прозрачное за квадратный метр?"},
    ]}).json()["answers"]
    assert "10 000" in swapped[0]["answer"] and "4 500" in swapped[1]["answer"]


def test_quality_batch_reports_needs_review_as_blocker(app_client):
    version = kb_version(app_client)
    result = app_client.post("/api/v1/quality/batch", json={"dataset_id": "ds-a", "kb_version": version, "dialogs": [
        {"id": "a", "client": "Почём стекло серое?", "manager": "Стекло серое: 13 000 тг."},
        {"id": "b", "client": "Сколько стоит стеклопакет?", "manager": "30 000 тг."},
    ]}).json()
    assert result["counts"] == {"OK": 0, "ERROR": 1, "NEEDS_REVIEW": 1}
    assert result["complete"] is False and result["export_blockers"] == ["needs_review:b"]


def test_catalog_routes(app_client):
    search = app_client.get("/api/v1/catalog/search", params={"dataset_id": "ds-a", "q": "калёное стекло"}).json()
    assert search["status"] == "ambiguous" and len(search["candidates"]) == 4
    product = app_client.get("/api/v1/catalog/products/riflenoe-prozrachnoe-8", params={"dataset_id": "ds-a"}).json()
    assert {p["price_type"]: p["amount_tg"] for p in product["prices"]} == {"per_m2": None, "per_sheet": "170000.00"}
    rules = app_client.get("/api/v1/catalog/rules", params={"dataset_id": "ds-a"}).json()
    assert {r["rule_id"] for r in rules} == {"r1", "r2", "r3", "r4", "r5", "r6", "r7"}
    missing = app_client.get("/api/v1/catalog", params={"dataset_id": "unknown"})
    assert missing.status_code == 404 and missing.json()["code"] == "DATASET_NOT_FOUND"
    assert set(missing.json()) == {"code", "message_ru", "field_errors", "conflict_objects", "retryable", "correlation_id"}
