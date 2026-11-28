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


def test_actual_parser_preserves_unknown_items_and_quantities(runtime):
    client, _, workspace = runtime
    d = workspace["dataset_id"]
    basket = post(client, "/baskets", dict(dataset_id=d, customer_ref="C-runtime",
        request_text="2 шт стекло 6 мм прозрачное 450×370 мм; неизвестная ручка XYZ без цены"))
    job = post(client, f"/baskets/{basket['basket_id']}/parse", dict(dataset_id=d,
        expected_version=0, operator="manager", note="Разобрать исходную заявку"))
    wait_job(client, job)
    basket = post(client, f"/baskets/{basket['basket_id']}/apply-parse", dict(dataset_id=d,
        expected_version=0, operator="manager", job_id=job["job_id"]))
    assert len(basket["lines"]) == 2 and basket["total_tg"] is None
    assert basket["lines"][0]["request"]["quantity"] == 2
    assert basket["lines"][1]["request"] is None and basket["lines"][1]["clarification"]


def test_actual_revision_and_measurement_make_order_stale(runtime):
    client, _, workspace = runtime
    d = workspace["dataset_id"]
    q, _ = quote(client, d)
    rid = q["candidate_refs"][0]["remnant_id"]
    sheet = action(client, order(client, d, q, rid), "confirm")
    revised = post(client, f"/quotes/{q['quote_id']}/revise", dict(dataset_id=d,
        expected_revision=q["revision"], changes=dict(dimensions=dict(length_mm=451, width_mm=370))))
    assert revised["total_tg"] == "1991.76" and revised["revision"] == q["revision"] + 1
    stale = client.get(f"/api/v1/order-sheets/{sheet['order_id']}", params={"dataset_id": d}).json()
    assert stale["quote_state"] == "stale" and stale["offer"] is None
    old = client.get(f"/api/v1/quotes/{q['quote_id']}", params={"dataset_id": d, "revision": 1}).json()
    assert old["total_tg"] == "1988.00"
    second, _ = quote(client, d)
    bound = action(client, order(client, d, second, rid), "confirm")
    r = client.get(f"/api/v1/remnants/{rid}", params={"dataset_id": d}).json()
    response = client.patch(f"/api/v1/remnants/{rid}/measurement", json=dict(dataset_id=d,
        expected_version=r["version"], dimensions=dict(length_mm=r["dimensions"]["length_mm"] - 1,
        width_mm=r["dimensions"]["width_mm"]), reason="Повторный замер"))
    assert response.status_code == 200, response.text
    assert client.get(f"/api/v1/order-sheets/{bound['order_id']}", params={"dataset_id": d}).json()["quote_state"] == "stale"


def test_actual_c2_mutation_rolls_back_if_platform_completion_fails(runtime):
    from glassflow.core.domain_sources import OrderSource
    from glassflow.core.errors import AppError
    client, _, workspace = runtime
    d = workspace["dataset_id"]
    q, _ = quote(client, d)
    rid = q["candidate_refs"][0]["remnant_id"]
    sheet = action(client, order(client, d, q, rid), "confirm")
    class InjectFailureAfterActualC2Reserve(OrderSource):
        def reserve(self, *args, **kwargs):
            super().reserve(*args, **kwargs)
            raise AppError(409, "INJECTED_AFTER_REAL_RESERVE", "Fault injection for rollback proof")
    client.app.state.services.order_source = InjectFailureAfterActualC2Reserve()
    response = client.post(f"/api/v1/order-sheets/{sheet['order_id']}/reserve", json=dict(dataset_id=d,
        expected_version=sheet["version"], operator="manager"), headers={"Idempotency-Key": "rollback"})
    assert response.status_code == 409
    r = client.get(f"/api/v1/remnants/{rid}", params={"dataset_id": d}).json()
    assert r["status"] == "available" and r["version"] == 0
    client.app.state.services.order_source = OrderSource()
    assert action(client, sheet, "reserve")["reservation"]["state"] == "active"


def test_new_ids_changed_input_without_labels_and_real_partial_export(runtime):
    import csv
    import io
    from pathlib import Path
    client, _, _ = runtime
    root = Path(__file__).resolve().parents[2]
    pack = root / "inputs/PACK_for_teams"
    files = []
    for relative, prefix, columns in (
        ("1_ostatki/stock_open.csv", "ALT-R-", ["remnant_id"]),
        ("1_ostatki/orders_open.csv", "ALT-P-", ["part_id", "order_id"]),
        ("2_assistant_crm/applications_open.csv", "ALT-A-", ["app_id", "client_id"]),
        ("2_assistant_crm/questions_open.csv", "ALT-Q-", ["id"]),
        ("2_assistant_crm/dialogs_open.csv", "ALT-D-", ["id"]),
    ):
        reader = csv.DictReader(io.StringIO((pack / relative).read_text(encoding="utf-8-sig")))
        headers = [c for c in reader.fieldnames if c != "вернулся_за_60_дней"]
        rows = list(reader)
        for row in rows:
            for column in columns:
                row[column] = prefix + row[column]
            row.pop("вернулся_за_60_дней", None)
            if "длина_мм" in row:
                row["длина_мм"] = str(int(row["длина_мм"]) + (7 if "stock" in relative else 1))
        if "questions" in relative:
            rows[0]["question"] = "Сколько стоит стекло 6 мм прозрачное 451×370 мм с кромкой по всем сторонам?"
        if "dialogs" in relative:
            rows[0]["client"], rows[0]["manager"] = "Почём зеркало 4 мм?", "Цена 99999 тг."
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(reversed(rows))
        files.append(("files", (Path(relative).name, stream.getvalue().encode("utf-8"))))
    files.extend(("files", (Path(relative).name, (pack / relative).read_bytes())) for relative in (
        "1_ostatki/materials.csv", "2_assistant_crm/ksm_knowledge_base.json"))
    preview = client.post("/api/v1/imports/preview", files=files).json()
    assert not preview["errors"], preview
    source = post(client, f"/imports/{preview['import_id']}/commit", dict(name="Changed inputs without labels"))
    d = source["dataset_id"]
    buyer = client.post("/api/v1/buyers/import", params={"dataset_id": d}, files={
        "file": ("buyers.csv", (root / "data/buyers/buyers.platform.csv").read_bytes()),
        "evidence": ("evidence.json", (root / "data/buyers/evidence.platform.json").read_bytes())},
        headers={"Idempotency-Key": "new-source-buyers"}).json()
    assert buyer["status"] == "verified", buyer
    job = post(client, "/runs", dict(dataset_id=d, config_version="changed-input-test",
        buyer_registry_version=buyer["version"], ai_profile="local_limited",
        solver_config=dict(profile="quick", time_limit_seconds=5, workers=1)))
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        run = client.get(f"/api/v1/runs/{job['run_id']}").json()
        if run["status"] != "running":
            break
        time.sleep(.1)
    assert run["status"] == "completed", run
    exported = post(client, f"/runs/{job['run_id']}/export")
    assert exported["status"] == "partial" and "verdicts.csv" not in exported["files"]
    assert all(name in exported["files"] for name in ("solution.csv", "answers.csv", "picks.csv", "sale_cards.csv"))
    answers = list(csv.DictReader(io.StringIO(client.get(exported["files"]["answers.csv"]).text)))
    assert all(row["id"].startswith("ALT-Q-") for row in answers)
    assert "1 991" in next(r["answer"] for r in answers if r["id"] == "ALT-Q-Q01")
    manifest = client.get(exported["files"]["manifest.json"]).json()
    assert manifest["official_accuracy"] == {"assistant": None, "crm": None, "quality": None}
    assert manifest["validators"]["cutting_official"]["passed"]
