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
    # Merely presenting a printed version cannot authorize a stale physical reserve.
    reserve = client.post(
        f"/api/v1/remnants/{piece['remnant_id']}/reserve",
        json={
            "dataset_id": d,
            "expected_version": label["printed_version"],
            "owner_context": "stale-label",
            "material_id": piece["material_id"],
            "dimensions": {"length_mm": 10, "width_mm": 10},
        },
        headers={"Idempotency-Key": "old-label-cannot-reserve"},
    )
    assert reserve.status_code == 409 and reserve.json()["code"] == "VERSION_CONFLICT"
    assert (
        client.get(f"/api/v1/remnants/{piece['remnant_id']}", params={"dataset_id": d}).json()["status"]
        == "available"
    )
    assert client.get(f"/api/v1/piece-labels/{lid}", params={"dataset_id": source}).status_code == 404
    stale = client.post("/api/v1/piece-labels", json=body, headers={"Idempotency-Key": "print-stale"})
    assert stale.status_code == 409
    immutable = client.get(f"/api/v1/piece-labels/{lid}", params={"dataset_id": d}).json()
    assert immutable == label
    with pytest.raises(IntegrityError):
        with client.app.state.session_factory.begin() as session:
            row = session.get(ObjectRow, (d, "piece_label", lid))
            row.data = {"changed": True}


def test_source_labels_blocked_and_actual_pdf_contains_version_and_cyrillic(runtime, tmp_path):
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
    (tmp_path / "piece-label.pdf").write_bytes(result.content)


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


def test_real_confirmed_order_pdf_keeps_snapshot_after_cancel(runtime, tmp_path):
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
    (tmp_path / "order-issue.pdf").write_bytes(pdf.content)
    action(order, "cancel")
    assert client.get(url, params={"dataset_id": d}).json() == document
    assert client.get(f"/api/v1/remnants/{rid}", params={"dataset_id": d}).json()["status"] == "available"


def test_real_checked_basket_document_has_current_pieces_locations_and_no_state_transition(runtime, tmp_path):
    import time

    client, _, d = runtime
    versions = client.get("/api/v1/catalog/versions", params={"dataset_id": d}).json()
    kb = next(v["kb_version"] for v in versions if v["current"])
    quotes, lines = [], []
    for index, dims in enumerate([(200, 100), (220, 120)]):
        request = dict(
            dataset_id=d,
            customer_id="basket-doc-customer",
            catalog_product_id="steklo-6-prozrachnoe",
            kb_version=kb,
            dimensions={"length_mm": dims[0], "width_mm": dims[1]},
            quantity=index + 1,
            processing={"kind": "none"},
            inventory_mode="none",
        )
        q = accepted(client, "/quotes", request, f"basket-doc-quote-{index}")
        q = accepted(
            client,
            f"/quotes/{q['quote_id']}/confirm",
            dict(dataset_id=d, expected_revision=q["revision"], confirmed_by="doc-manager"),
            f"basket-doc-confirm-{index}",
        )
        quotes.append(q)
        lines.append(
            {"line_id": f"changed-doc-line-{index}", "text": f"Реальная позиция {index}", "request": request}
        )
    basket = accepted(
        client,
        "/baskets",
        dict(
            dataset_id=d,
            customer_ref="basket-doc-customer",
            request_text="Проверка листа склада для двух позиций",
            lines=lines,
        ),
        "basket-doc-create",
    )
    binding = dict(
        dataset_id=d,
        expected_version=basket["version"],
        operator="doc-manager",
        lines=[
            dict(line_id=line["line_id"], quote_id=q["quote_id"], quote_revision=q["revision"])
            for line, q in zip(lines, quotes, strict=True)
        ],
    )
    job = accepted(client, f"/baskets/{basket['basket_id']}/selection", binding, "basket-doc-selection")
    end = time.monotonic() + 30
    while time.monotonic() < end:
        job = client.get(f"/api/v1/jobs/{job['job_id']}").json()
        if job["state"] in {"completed", "failed"}:
            break
        time.sleep(0.05)
    assert job["state"] == "completed", job
    chosen = job["result"]
    basket = accepted(
        client,
        f"/baskets/{basket['basket_id']}/bind",
        binding
        | {"selection_ref": chosen["selection_ref"], "selection_version": chosen["selection_version"]},
        "basket-doc-bind",
    )
    for action in ["confirm", "reserve", "warehouse-check"]:
        basket = accepted(
            client,
            f"/baskets/{basket['basket_id']}/{action}",
            dict(
                dataset_id=d,
                expected_version=basket["version"],
                operator="doc-manager",
                note="Лично сверены все позиции и куски",
            ),
            f"basket-doc-{action}",
        )
    assert basket["state"] == "checked"
    body = dict(
        dataset_id=d,
        subject_type="basket",
        subject_id=basket["basket_id"],
        expected_version=basket["version"],
        operator="doc-manager",
    )
    document = accepted(client, "/warehouse-documents", body, "basket-doc-sheet")
    assert document["snapshot"]["warehouse_pieces"]
    for piece in document["snapshot"]["warehouse_pieces"]:
        current = client.get(
            f"/api/v1/remnants/{piece['remnant']['remnant_id']}", params={"dataset_id": d}
        ).json()
        assert piece["remnant"] == current and current["status"] == "reserved"
    pdf = client.get(f"/api/v1/warehouse-documents/{document['document_id']}/pdf", params={"dataset_id": d})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    text = " ".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
    for piece in document["snapshot"]["warehouse_pieces"]:
        assert piece["remnant"]["remnant_id"] in text and piece["remnant"]["location_raw"] in text
        for part in piece["parts"]:
            assert document["snapshot"]["part_labels"][part["part_id"]] in text
            assert part["part_id"] not in text
    assert set(document["snapshot"]["part_labels"].values()) == {
        "Позиция 1, экземпляр 1",
        "Позиция 2, экземпляр 1",
        "Позиция 2, экземпляр 2",
    }
    assert "Стекло 6 мм прозрачное" in text
    assert (
        client.get(
            f"/api/v1/warehouse-documents/{document['document_id']}/pdf", params={"dataset_id": d}
        ).content
        == pdf.content
    )
    (tmp_path / "basket-issue.pdf").write_bytes(pdf.content)
    assert client.get(f"/api/v1/baskets/{basket['basket_id']}", params={"dataset_id": d}).json() == basket
    assert accepted(client, "/warehouse-documents", body, "basket-doc-sheet") == document
    piece = document["snapshot"]["warehouse_pieces"][0]["remnant"]
    updated = client.patch(
        f"/api/v1/remnants/{piece['remnant_id']}",
        json=dict(dataset_id=d, expected_version=piece["version"], location_raw="Новое место после печати"),
    )
    assert updated.status_code == 200, updated.text
    stale = client.post(
        "/api/v1/warehouse-documents", json=body, headers={"Idempotency-Key": "stale-basket-doc"}
    )
    assert stale.status_code == 409
    assert (
        client.get(f"/api/v1/warehouse-documents/{document['document_id']}", params={"dataset_id": d}).json()
        == document
    )


def test_printed_long_rows_paginate_without_losing_content(tmp_path):
    # Renderer boundary only; this synthetic text is not a measured production order.
    from glassflow.modules.insights.documents import pdf_document

    expected = [f"Деталь-{index}: 450×370 мм; стеллаж А" for index in range(180)]
    content = pdf_document("Тест длинного складского задания", [("Детали", "; ".join(expected))])
    reader = PdfReader(io.BytesIO(content))
    text = " ".join(page.extract_text() for page in reader.pages)
    assert len(reader.pages) > 1
    assert all(f"Деталь-{index}:" in text for index in range(180))
    (tmp_path / "long-issue.pdf").write_bytes(content)
