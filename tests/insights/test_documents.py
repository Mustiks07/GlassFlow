import io
import json

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy.exc import IntegrityError

from glassflow.core.models import ObjectRow
from glassflow.main import create_app


def accepted(client, path, body, key):
    response = client.post("/api/v1" + path, json=body, headers={"Idempotency-Key": key})
    assert response.status_code in {200, 202}, response.text
    return response.json()


@pytest.fixture()
def runtime(tmp_path):
    with TestClient(create_app(tmp_path, testing=True)) as client:
        client.get("/api/v1/session")
        source = client.post("/api/v1/datasets/demo", headers={"Idempotency-Key": "docs-original"}).json()
        workspace = client.post(
            f"/api/v1/datasets/{source['dataset_id']}/working-copy",
            json={},
            headers={"Idempotency-Key": "docs-copy"},
        ).json()
        yield client, source["dataset_id"], workspace["dataset_id"]


def test_label_looks_up_current_piece_but_never_authorizes_old_version(runtime):
    client, source, d = runtime
    piece = client.get("/api/v1/remnants", params={"dataset_id": d}).json()[0]
    body = {
        "dataset_id": d,
        "remnant_id": piece["remnant_id"],
        "expected_version": piece["version"],
        "operator": "test-operator",
    }
    response = client.post("/api/v1/piece-labels", json=body, headers={"Idempotency-Key": "print-first"})
    assert response.status_code == 200, response.text
    label = response.json()
    lid = label["label_id"]
    assert json.loads(label["scan_payload"])["remnant_id"] == piece["remnant_id"]
    assert (
        client.post("/api/v1/piece-labels", json=body, headers={"Idempotency-Key": "print-first"}).json()[
            "label_id"
        ]
        == lid
    )
    dims = piece["dimensions"] | {"length_mm": piece["dimensions"]["length_mm"] + 1}
    updated = client.patch(
        f"/api/v1/remnants/{piece['remnant_id']}/measurement",
        json={
            "dataset_id": d,
            "expected_version": piece["version"],
            "dimensions": dims,
            "reason": "Повторный реальный замер в тесте",
        },
    )
    assert updated.status_code == 200, updated.text
    view = client.get(f"/api/v1/piece-labels/{lid}/resolve", params={"dataset_id": d}).json()
    assert view["changed"] and view["label"]["printed_version"] == 0 and view["current"]["version"] == 1
    assert view["mutation_authorized_by_label"] is False
    assert client.get(f"/api/v1/piece-labels/{lid}", params={"dataset_id": source}).status_code == 404
    stale = client.post("/api/v1/piece-labels", json=body, headers={"Idempotency-Key": "print-stale"})
    assert stale.status_code == 409
    immutable = client.get(f"/api/v1/piece-labels/{lid}", params={"dataset_id": d}).json()
    assert immutable == label
    with pytest.raises(IntegrityError):
        with client.app.state.session_factory.begin() as session:
            row = session.get(ObjectRow, (d, "piece_label", lid))
            row.data = {"changed": True}


def test_source_labels_blocked_and_actual_pdf_contains_version_and_cyrillic(runtime):
    client, source, d = runtime
    piece = client.get("/api/v1/remnants", params={"dataset_id": d}).json()[0]
    body = {
        "dataset_id": source,
        "remnant_id": piece["remnant_id"],
        "expected_version": 0,
        "operator": "test-operator",
    }
    assert (
        client.post(
            "/api/v1/piece-labels", json=body, headers={"Idempotency-Key": "no-source-print"}
        ).status_code
        == 409
    )
    body["dataset_id"] = d
    label = client.post("/api/v1/piece-labels", json=body, headers={"Idempotency-Key": "pdf-label"}).json()
    result = client.get(f"/api/v1/piece-labels/{label['label_id']}/pdf", params={"dataset_id": d})
    assert result.status_code == 200 and result.headers["content-type"] == "application/pdf"
    pdf = PdfReader(io.BytesIO(result.content))
    text = " ".join(p.extract_text() for p in pdf.pages)
    assert (
        len(pdf.pages) == 1 and "Бирка остатка" in text and piece["remnant_id"] in text and "Версия" in text
    )


def test_issue_sheet_cannot_turn_a_draft_into_a_confirmed_warehouse_action(runtime):
    client, _, d = runtime
    order = client.post(
        "/api/v1/order-sheets",
        json={"dataset_id": d, "customer_ref": "test-client", "request_text": "Draft only"},
        headers={"Idempotency-Key": "new-draft"},
    ).json()
    response = client.post(
        "/api/v1/warehouse-documents",
        json={
            "dataset_id": d,
            "subject_type": "order",
            "subject_id": order["order_id"],
            "expected_version": 0,
            "operator": "test-operator",
        },
        headers={"Idempotency-Key": "draft-doc"},
    )
    assert response.status_code == 409 and response.json()["code"] == "ORDER_NOT_READY"
    assert (
        client.get(f"/api/v1/order-sheets/{order['order_id']}", params={"dataset_id": d}).json()[
            "quote_state"
        ]
        == "missing"
    )


def test_real_confirmed_order_pdf_keeps_snapshot_after_cancel(runtime):
    client, _, d = runtime
    versions = client.get("/api/v1/catalog/versions", params={"dataset_id": d}).json()
    kb = next(v["kb_version"] for v in versions if v["current"])
    quote = accepted(
        client,
        "/quotes",
        {
            "dataset_id": d,
            "catalog_product_id": "steklo-6-prozrachnoe",
            "kb_version": kb,
            "customer_id": "doc-customer",
            "quantity": 1,
            "dimensions": {"length_mm": 450, "width_mm": 370},
            "processing": {"kind": "euro_edge", "sides": "all"},
            "inventory_mode": "free_whole_remnants",
        },
        "doc-quote",
    )
    quote = accepted(
        client,
        f"/quotes/{quote['quote_id']}/confirm",
        {"dataset_id": d, "expected_revision": quote["revision"], "confirmed_by": "doc-manager"},
        "doc-quote-confirm",
    )
    rid = quote["candidate_refs"][0]["remnant_id"]
    piece = client.get(f"/api/v1/remnants/{rid}", params={"dataset_id": d}).json()
    order = accepted(
        client,
        "/order-sheets",
        {"dataset_id": d, "customer_ref": "doc-customer", "request_text": "Проверка листа выдачи"},
        "doc-order",
    )

    def action(sheet, operation, **extras):
        return accepted(
            client,
            f"/order-sheets/{sheet['order_id']}/{operation}",
            {"dataset_id": d, "expected_version": sheet["version"], "operator": "doc-manager", **extras},
            operation,
        )

    order = action(
        order,
        "bind",
        quote_id=quote["quote_id"],
        quote_revision=quote["revision"],
        remnant_id=rid,
        remnant_version=piece["version"],
    )
    order = action(order, "confirm")
    body = {
        "dataset_id": d,
        "subject_type": "order",
        "subject_id": order["order_id"],
        "expected_version": order["version"],
        "operator": "doc-manager",
    }
    document = accepted(client, "/warehouse-documents", body, "issue-verified")
    url = f"/api/v1/warehouse-documents/{document['document_id']}"
    pdf = client.get(url + "/pdf", params={"dataset_id": d})
    assert pdf.status_code == 200
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert rid in text and "450" in text and "370" in text and "Лист задания складу" in text
    action(order, "cancel")
    assert client.get(url, params={"dataset_id": d}).json() == document
    assert client.get(f"/api/v1/remnants/{rid}", params={"dataset_id": d}).json()["status"] == "available"
