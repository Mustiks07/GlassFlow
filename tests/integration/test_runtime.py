"""Actual production composition: HTTP, imported bytes, C2/C3 services and SQLite.

No synthetic source/reservation adapters. Browser checks are a separate suite.
"""

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from glassflow.main import create_app


def post(client, path, body=None, key=None):
    response = client.post("/api/v1" + path, json=body,
        headers={"Idempotency-Key": key or f"{path}:{time.time_ns()}"})
    assert response.status_code in {200, 202}, response.text
    return response.json()


@pytest.fixture()
def runtime(tmp_path):
    app = create_app(tmp_path, testing=True)
    with TestClient(app) as client:
        client.get("/api/v1/session")
        source = post(client, "/datasets/demo")
        workspace = post(client, f"/datasets/{source['dataset_id']}/working-copy", {})
        yield client, source, workspace


def quote(client, dataset_id, customer="C-runtime", **changes):
    versions = client.get("/api/v1/catalog/versions", params={"dataset_id": dataset_id}).json()
    kb = next(v["kb_version"] for v in versions if v["current"])
    request = dict(dataset_id=dataset_id, catalog_product_id="steklo-6-prozrachnoe", kb_version=kb,
        customer_id=customer, dimensions=dict(length_mm=450, width_mm=370), quantity=1,
        processing=dict(kind="euro_edge", sides="all"), inventory_mode="free_whole_remnants") | changes
    value = post(client, "/quotes", request)
    confirmed = post(client, f"/quotes/{value['quote_id']}/confirm", dict(dataset_id=dataset_id,
        expected_revision=value["revision"], confirmed_by="runtime-manager"))
    return confirmed, request


def order(client, d, q, rid):
    value = post(client, "/order-sheets", dict(dataset_id=d, customer_ref="C-runtime", request_text="Реальная заявка"))
    r = client.get(f"/api/v1/remnants/{rid}", params={"dataset_id": d}).json()
    return action(client, value, "bind", quote_id=q["quote_id"], quote_revision=q["revision"],
                  remnant_id=rid, remnant_version=r["version"])


def action(client, subject, operation, kind="order-sheets", **extra):
    ref = subject["order_id"] if kind == "order-sheets" else subject["basket_id"]
    return post(client, f"/{kind}/{ref}/{operation}", dict(dataset_id=subject["dataset_id"],
        expected_version=subject["version"], operator="runtime-manager", note="Личная проверка", **extra))


def wait_job(client, job):
    deadline = time.monotonic() + 75
    while time.monotonic() < deadline:
        value = client.get(f"/api/v1/jobs/{job['job_id']}").json()
        if value["state"] not in {"queued", "running"}:
            assert value["state"] == "completed", value
            return value["result"]
        time.sleep(.1)
    pytest.fail("Actual worker did not finish")


def complete_use(client, subject, kind):
    body = dict(dataset_id=subject["dataset_id"], subject_type=kind, subject_id=subject[f"{kind}_id"],
        expected_version=subject["version"], execution_ref="new-execution", execution_version=1,
        operator="runtime-manager", note="Оператор сверил фактические размеры", discrepancy_reason="")
    template = post(client, "/cutting/execution-template", body)
    assert template["physical_execution_confirmed"] is False
    execution = post(client, "/cutting/executions", body | {k: template[k] for k in ("parts", "placements")})
    body |= {k: execution[k] for k in ("execution_ref", "execution_version")}
    preview = post(client, "/material-use/preview", body)
    assert preview["actual_area_mm2"] > 0
    usage = post(client, "/material-use", body)
    assert post(client, "/material-use", body)["usage_id"] == usage["usage_id"]
    summary = client.get("/api/v1/material-use/summary", params={"dataset_id": body["dataset_id"]}).json()
    assert summary["confirmation_count"] == 1
    return usage


def test_import_quote_atomic_order_reservation_warehouse_actual_use_and_replay(runtime):
    client, source, workspace = runtime
    d = workspace["dataset_id"]
    assert client.get("/api/v1/ready").json()["business_modules_ready"]
    q, _ = quote(client, d)
    assert q["total_tg"] == "1988.00" and not q["preliminary"]
    rid = q["candidate_refs"][0]["remnant_id"]
    sheet = action(client, order(client, d, q, rid), "confirm")
    sheet = action(client, sheet, "reserve")
    assert sheet["reservation"]["state"] == "active"
    sheet = action(client, sheet, "warehouse-check")
    sheet = action(client, sheet, "handover")
    usage = complete_use(client, sheet, "order")
    assert usage["receipt"]["reservation_state"] == "consumed"
    assert client.get(f"/api/v1/remnants/{rid}", params={"dataset_id": d}).json()["status"] == "consumed"
    assert client.get(f"/api/v1/remnants/{rid}", params={"dataset_id": source["dataset_id"]}).json()["status"] == "available"


def test_actual_two_managers_same_piece_and_changed_owner(runtime):
    client, _, workspace = runtime
    d = workspace["dataset_id"]
    q, _ = quote(client, d)
    rid = q["candidate_refs"][0]["remnant_id"]
    sheets = [action(client, order(client, d, q, rid), "confirm") for _ in range(2)]
    def reserve(sheet):
        return client.post(f"/api/v1/order-sheets/{sheet['order_id']}/reserve", json=dict(dataset_id=d,
            expected_version=sheet["version"], operator="manager"), headers={"Idempotency-Key": sheet["order_id"]})
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(reserve, sheets))
    assert sorted(r.status_code for r in responses) == [200, 409]
    other, _ = quote(client, d, customer="C-other")
    sheet = post(client, "/order-sheets", dict(dataset_id=d, customer_ref="C-runtime", request_text="Владелец"))
    response = client.post(f"/api/v1/order-sheets/{sheet['order_id']}/bind", json=dict(dataset_id=d,
        expected_version=0, operator="manager", quote_id=other["quote_id"], quote_revision=1,
        remnant_id=other["candidate_refs"][0]["remnant_id"], remnant_version=0), headers={"Idempotency-Key": "owner"})
    assert response.status_code == 409 and response.json()["code"] == "QUOTE_CUSTOMER_MISMATCH"


def test_actual_basket_joint_worker_reserve_and_use(runtime):
    client, _, workspace = runtime
    d = workspace["dataset_id"]
    quotes = [quote(client, d, inventory_mode="none", dimensions=dict(length_mm=200, width_mm=100), quantity=2),
              quote(client, d, inventory_mode="none", dimensions=dict(length_mm=220, width_mm=120), quantity=1)]
    lines = [dict(line_id=f"line-{i}", text=f"Позиция {i}", request=r) for i, (_, r) in enumerate(quotes)]
    basket = post(client, "/baskets", dict(dataset_id=d, customer_ref="C-runtime", request_text="Две позиции", lines=lines))
    binding = dict(dataset_id=d, expected_version=basket["version"], operator="manager",
        lines=[dict(line_id=f"line-{i}", quote_id=q["quote_id"], quote_revision=q["revision"]) for i, (q, _) in enumerate(quotes)])
    result = wait_job(client, post(client, f"/baskets/{basket['basket_id']}/selection", binding))
    basket = post(client, f"/baskets/{basket['basket_id']}/bind", binding | {
        "selection_ref": result["selection_ref"], "selection_version": result["selection_version"]})
    assert basket["state"] == "ready", basket
    for operation in ("confirm", "reserve", "warehouse-check", "handover"):
        basket = action(client, basket, operation, kind="baskets")
    complete_use(client, basket, "basket")
