"""U01 coordinator acceptance with explicit transactional C2/C3 test adapters, not full product E2E."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from glassflow.contracts.intelligence import Quote
from glassflow.contracts.orders import OrderFacts, OrderReservation
from glassflow.core.errors import AppError
from glassflow.core.models import ObjectRow
from glassflow.core.uow import write_transaction
from glassflow.main import create_app


class SyntheticOrderSource:
    """DB-backed fixture guarantees mutations roll back with the caller UoW."""

    def capture(self, session, dataset_id, quote_id, remnant_id, order_id):
        assert quote_id == "synthetic-Q" and remnant_id == "synthetic-R"
        return OrderFacts.model_validate(session.get(ObjectRow, (dataset_id, "synthetic", "facts")).data)

    def reserve(self, session, facts, order_id, order_revision):
        row = session.get(ObjectRow, (facts.dataset_id, "synthetic", "facts"))
        current = OrderFacts.model_validate(row.data)
        if current.remnant.status != "available" or current.remnant.version != facts.remnant.version:
            raise AppError(409, "SYNTHETIC_RESERVED", "Test conflict", conflicts=["alternative:R-other"])
        current.remnant.status, current.remnant.version = "reserved", current.remnant.version + 1
        row.data = current.model_dump(mode="json")
        ref = OrderReservation(dataset_id=facts.dataset_id, reservation_id="synthetic-reservation",
                               order_id=order_id, order_revision=order_revision,
                               remnant_id=current.remnant.remnant_id,
                               remnant_version=current.remnant.version, state="active")
        session.add(ObjectRow(dataset_id=facts.dataset_id, kind="synthetic", id=ref.reservation_id,
                              version=0, data=ref.model_dump()))
        return ref

    def reservation(self, session, dataset_id, reservation_id):
        return OrderReservation.model_validate(session.get(ObjectRow, (dataset_id, "synthetic", reservation_id)).data)

    def release(self, session, reservation):
        ref = self.reservation(session, reservation.dataset_id, reservation.reservation_id)
        assert ref.order_id == reservation.order_id
        row = session.get(ObjectRow, (ref.dataset_id, "synthetic", "facts"))
        facts = OrderFacts.model_validate(row.data)
        facts.remnant.status, facts.remnant.version = "available", facts.remnant.version + 1
        row.data = facts.model_dump(mode="json")
        ref.state = "released"
        session.get(ObjectRow, (ref.dataset_id, "synthetic", ref.reservation_id)).data = ref.model_dump()
        return ref


def setup(client, imported, services):
    d = client.post(f"/api/v1/datasets/{imported['dataset_id']}/working-copy", json={},
                    headers={"Idempotency-Key": "order-workspace"}).json()["dataset_id"]
    services.order_source = SyntheticOrderSource()
    facts = dict(dataset_id=d, quote=dict(dataset_id=d, quote_id="synthetic-Q", revision=1,
        status="ready", components=[], total_tg="1988", preliminary=False, customer_id="C-test",
        material_mapping_status="confirmed", material_id="synthetic-clear"),
        remnant=dict(dataset_id=d, remnant_id="synthetic-R", material_id="synthetic-clear",
                     dimensions=dict(length_mm=1000, width_mm=1000), defect=False, location_raw="",
                     status="available", version=0), requested_dimensions=dict(length_mm=450, width_mm=370),
        quantity=1, quote_customer_ref="C-test", kb_version="synthetic-kb1", mapping_version="synthetic-map1", compatible=True,
        alternative_remnant_ids=["synthetic-alternative"])
    with write_transaction(client.app.state.session_factory) as session:
        session.add(ObjectRow(dataset_id=d, kind="synthetic", id="facts", version=0, data=facts))
    return d


def new_order(client, d, key):
    result = client.post("/api/v1/order-sheets", json=dict(dataset_id=d, customer_ref="C-test",
                                                         request_text="Synthetic order request"),
                         headers={"Idempotency-Key": key})
    assert result.status_code == 200, result.text
    return result.json()


def command(client, sheet, action, key=None, **extra):
    return client.post(f"/api/v1/order-sheets/{sheet['order_id']}/{action}",
                        json=dict(dataset_id=sheet["dataset_id"], expected_version=sheet["version"],
                                  operator="test-manager", **extra),
                        headers={"Idempotency-Key": key or f"{action}:{sheet['version']}"})


def bound(client, d, key):
    sheet = new_order(client, d, key)
    response = command(client, sheet, "bind", quote_id="synthetic-Q", quote_revision=1,
                       remnant_id="synthetic-R", remnant_version=0)
    assert response.status_code == 200, response.text
    return response.json()


def test_two_managers_one_reservation_same_facts_forms_and_restart(client, imported, services):
    d = setup(client, imported, services)
    first, second = bound(client, d, "one"), bound(client, d, "two")
    assert first["offer"]["facts_hash"] == first["warehouse_task"]["facts_hash"]
    assert first["warehouse_task"]["location_known"] is False
    assert command(client, first, "reserve").status_code == 409
    first = command(client, first, "confirm").json()
    second = command(client, second, "confirm").json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda s: command(client, s, "reserve", key=f"reserve:{s['order_id']}"),
                                [first, second]))
    assert sorted(r.status_code for r in results) == [200, 409]
    winner = next(r.json() for r in results if r.status_code == 200)
    loser = next(r.json() for r in results if r.status_code == 409)
    assert "alternative:synthetic-alternative" in loser["conflict_objects"]
    assert winner["reservation"]["state"] == "active"
    original = first if winner["order_id"] == first["order_id"] else second
    replay = command(client, original, "reserve", key=f"reserve:{winner['order_id']}")
    assert replay.json() == winner
    assert command(client, winner, "handover").status_code == 409
    winner = command(client, winner, "warehouse-check", note="Human checked actual piece, test fixture").json()
    winner = command(client, winner, "handover").json()
    assert winner["lifecycle"] == "handed_over"
    with TestClient(create_app(client.app.state.data_dir, services, testing=True)) as restarted:
        saved = restarted.get(f"/api/v1/order-sheets/{winner['order_id']}", params={"dataset_id": d}).json()
        assert saved == winner
        events = restarted.get(f"/api/v1/order-sheets/{winner['order_id']}/history", params={"dataset_id": d}).json()
        assert [e["action"] for e in events].count("order.reserve") == 1
        assert events[-1]["sheet"] == winner
        assert events[-2]["note"].startswith("Human checked")


def test_changed_measurement_price_invalidates_and_preserves_confirmed_history(client, imported, services):
    d = setup(client, imported, services)
    sheet = command(client, bound(client, d, "change"), "confirm").json()
    original = sheet
    with write_transaction(client.app.state.session_factory) as session:
        row = session.get(ObjectRow, (d, "synthetic", "facts"))
        facts = OrderFacts.model_validate(row.data)
        facts.quote.revision, facts.quote.total_tg, facts.kb_version = 2, "1991.76", "synthetic-kb2"
        facts.requested_dimensions.length_mm = 451
        facts.remnant.version = 1
        row.data = facts.model_dump(mode="json")
    conflict = command(client, sheet, "reserve")
    assert conflict.status_code == 409 and conflict.json()["code"] == "ORDER_STALE"
    stale = client.get(f"/api/v1/order-sheets/{sheet['order_id']}", params={"dataset_id": d}).json()
    assert stale["quote_state"] == "stale" and stale["offer"] is None and stale["warehouse_task"] is None
    events = client.get(f"/api/v1/order-sheets/{sheet['order_id']}/history", params={"dataset_id": d}).json()
    confirmed = next(e["sheet"] for e in events if e["action"] == "order.confirm")
    assert confirmed == original and confirmed["offer"]["quote"]["total_tg"] == "1988"
    refreshed = command(client, stale, "bind", quote_id="synthetic-Q", quote_revision=2,
                         remnant_id="synthetic-R", remnant_version=1).json()
    assert refreshed["revision"] == 2 and refreshed["quote_state"] == "draft"
    assert refreshed["offer"]["quote"]["total_tg"] == "1991.76"


def test_order_fail_closed_workspace_scope_and_release(client, imported, services):
    assert client.post("/api/v1/order-sheets", json=dict(dataset_id=imported["dataset_id"],
                       customer_ref="test", request_text="test"),
                       headers={"Idempotency-Key": "source-not-workspace"}).status_code == 409
    d = setup(client, imported, services)
    sheet = bound(client, d, "release")
    services.order_source = None
    assert command(client, sheet, "confirm").status_code == 503
    services.order_source = SyntheticOrderSource()
    sheet = command(client, sheet, "confirm").json()
    sheet = command(client, sheet, "reserve").json()
    assert command(client, sheet, "bind", quote_id="synthetic-Q", quote_revision=1,
                   remnant_id="synthetic-R", remnant_version=1).status_code == 409
    sheet = command(client, sheet, "release").json()
    assert sheet["reservation"]["state"] == "released" and sheet["offer"] is None
    sheet = command(client, sheet, "cancel").json()
    assert sheet["lifecycle"] == "cancelled"


def test_order_reserve_and_source_changes_share_rollback(client, imported, services):
    class ChangingSource(SyntheticOrderSource):
        def reserve(self, session, facts, order_id, order_revision):
            ref = super().reserve(session, facts, order_id, order_revision)
            row = session.get(ObjectRow, (facts.dataset_id, "synthetic", "facts"))
            changed = OrderFacts.model_validate(row.data)
            changed.quote.total_tg = "99999"
            row.data = changed.model_dump(mode="json")
            return ref

    d = setup(client, imported, services)
    sheet = command(client, bound(client, d, "rollback"), "confirm").json()
    services.order_source = ChangingSource()
    response = command(client, sheet, "reserve")
    assert response.status_code == 409 and response.json()["code"] == "RESERVATION_FACTS_CHANGED"
    with client.app.state.session_factory() as session:
        facts = OrderFacts.model_validate(session.get(ObjectRow, (d, "synthetic", "facts")).data)
        assert facts.remnant.status == "available" and facts.quote.total_tg == "1988"
        assert session.get(ObjectRow, (d, "synthetic", "synthetic-reservation")) is None


@pytest.mark.parametrize("owner,code", [("C-other", "QUOTE_CUSTOMER_MISMATCH"), (None, "QUOTE_CUSTOMER_REQUIRED"),
                                       ("missing", "QUOTE_CUSTOMER_REQUIRED")])
def test_bind_rejects_other_or_anonymous_quote_customer_without_mutations(client, imported, services, owner, code):
    d = setup(client, imported, services)
    sheet = new_order(client, d, "f1-unbound")
    with write_transaction(client.app.state.session_factory) as session:
        row = session.get(ObjectRow, (d, "synthetic", "facts"))
        row.data = ({k: v for k, v in row.data.items() if k != "quote_customer_ref"}
                    if owner == "missing" else {**row.data, "quote_customer_ref": owner, "quote": {**row.data["quote"], "customer_id": owner}})
    response = command(client, sheet, "bind", quote_id="synthetic-Q", quote_revision=1,
                       remnant_id="synthetic-R", remnant_version=0)
    assert response.status_code == 409 and response.json()["code"] == code
    saved = client.get(f"/api/v1/order-sheets/{sheet['order_id']}", params={"dataset_id": d}).json()
    assert saved == sheet and saved["quote_state"] == "missing"
    with client.app.state.session_factory() as session:
        assert session.get(ObjectRow, (d, "synthetic", "facts")).data["remnant"]["status"] == "available"
        assert session.get(ObjectRow, (d, "synthetic", "synthetic-reservation")) is None
    events = client.get(f"/api/v1/order-sheets/{sheet['order_id']}/history", params={"dataset_id": d}).json()
    assert [e["action"] for e in events] == ["order.create"]


@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize("owner,code", [("C-other", "QUOTE_CUSTOMER_MISMATCH"), (None, "QUOTE_CUSTOMER_REQUIRED")])
def test_customer_changed_before_confirm_or_reserve_is_durable_stale(client, imported, services, confirmed, owner, code):
    d = setup(client, imported, services)
    sheet = bound(client, d, "f1-current-owner")
    if confirmed:
        sheet = command(client, sheet, "confirm").json()
    with write_transaction(client.app.state.session_factory) as session:
        row = session.get(ObjectRow, (d, "synthetic", "facts"))
        # Isolate ownership from geometry/price and even quote revision.
        row.data = {**row.data, "quote_customer_ref": owner, "quote": {**row.data["quote"], "customer_id": owner}}
    response = command(client, sheet, "reserve" if confirmed else "confirm")
    assert response.status_code == 409 and response.json()["code"] == code
    url, params = f"/api/v1/order-sheets/{sheet['order_id']}", {"dataset_id": d}
    stale = client.get(url, params=params).json()
    assert stale["quote_state"] == stale["warehouse_state"] == "stale"
    assert stale["stale_code"] == code and stale["offer"] is None and stale["warehouse_task"] is None
    assert stale["facts"] == sheet["facts"]  # Original proof is retained, never reassigned.
    assert stale["version"] == sheet["version"] + 1
    assert command(client, stale, "confirm", key="f1-no-silent-reconfirm").status_code == 409
    assert command(client, stale, "reserve", key="f1-no-silent-rereserve").status_code == 409
    with client.app.state.session_factory() as session:
        data = session.get(ObjectRow, (d, "synthetic", "facts")).data
        assert data["quote_customer_ref"] == owner and data["remnant"]["status"] == "available"
        assert session.get(ObjectRow, (d, "synthetic", "synthetic-reservation")) is None
    events = client.get(url + "/history", params=params).json()
    assert events[-2]["sheet"] == sheet and events[-1]["action"] == "order.stale"
    if confirmed:
        assert events[-2]["action"] == "order.confirm"
        assert events[-2]["sheet"]["offer"]["confirmed"] is True
    with TestClient(create_app(client.app.state.data_dir, services, testing=True)) as restarted:
        assert restarted.get(url, params=params).json() == stale


@pytest.mark.parametrize("owner,canonical,code", [
    ("C-test", "C-test", None), ("C-other", "C-other", "QUOTE_CUSTOMER_MISMATCH"),
    ("C-test", "C-other", "QUOTE_CUSTOMER_INCONSISTENT"),
    ("C-test", None, "QUOTE_CUSTOMER_INCONSISTENT"), (None, None, "QUOTE_CUSTOMER_REQUIRED"),
])
def test_explicit_customer_attestation_agrees_with_extended_c3_quote(client, imported, services, owner, canonical, code):
    class SyntheticCustomerQuote(Quote):
        """Test compatibility with C3's additive customer_id, without editing C3 files."""
        customer_id: str | None = None

    class ExtendedSource(SyntheticOrderSource):
        def capture(self, session, dataset_id, quote_id, remnant_id, order_id):
            facts = super().capture(session, dataset_id, quote_id, remnant_id, order_id)
            facts.quote = SyntheticCustomerQuote(**{**facts.quote.model_dump(), "customer_id": canonical})
            facts.quote_customer_ref = owner
            return facts

    d = setup(client, imported, services)
    services.order_source = ExtendedSource()
    sheet = new_order(client, d, "f1-c3-compatible")
    response = command(client, sheet, "bind", quote_id="synthetic-Q", quote_revision=1,
                       remnant_id="synthetic-R", remnant_version=0)
    if code:
        assert response.status_code == 409 and response.json()["code"] == code
        with client.app.state.session_factory() as session:
            assert session.get(ObjectRow, (d, "synthetic", "synthetic-reservation")) is None
    else:
        assert response.status_code == 200, response.text
        sheet = command(client, response.json(), "confirm").json()
        reserved = command(client, sheet, "reserve")
        assert reserved.status_code == 200, reserved.text
        assert reserved.json()["facts"]["quote_customer_ref"] == sheet["customer_ref"]


def test_missing_legacy_ownership_is_not_assigned_on_read(client, imported, services):
    d = setup(client, imported, services)
    sheet = command(client, bound(client, d, "f1-legacy"), "confirm").json()
    with write_transaction(client.app.state.session_factory) as session:
        row = session.get(ObjectRow, (d, "order_sheet", sheet["order_id"]))
        row.data = {**row.data, "facts": {k: v for k, v in row.data["facts"].items() if k != "quote_customer_ref"}}
    url, params = f"/api/v1/order-sheets/{sheet['order_id']}", {"dataset_id": d}
    stale = client.get(url, params=params).json()
    assert stale["stale_code"] == "QUOTE_CUSTOMER_REQUIRED" and stale["offer"] is None
    assert stale["facts"]["quote_customer_ref"] is None
    refreshed = command(client, stale, "bind", quote_id="synthetic-Q", quote_revision=1,
                         remnant_id="synthetic-R", remnant_version=0)
    assert refreshed.status_code == 200 and refreshed.json()["quote_state"] == "draft"
    assert refreshed.json()["facts"]["quote_customer_ref"] == "C-test"


def test_owner_change_during_reservation_rolls_back_inventory(client, imported, services):
    class ChangingOwner(SyntheticOrderSource):
        def reserve(self, session, facts, order_id, order_revision):
            ref = super().reserve(session, facts, order_id, order_revision)
            row = session.get(ObjectRow, (facts.dataset_id, "synthetic", "facts"))
            row.data = {**row.data, "quote_customer_ref": "C-other", "quote": {**row.data["quote"], "customer_id": "C-other"}}
            return ref

    d = setup(client, imported, services)
    sheet = command(client, bound(client, d, "f1-atomic"), "confirm").json()
    services.order_source = ChangingOwner()
    response = command(client, sheet, "reserve")
    assert response.status_code == 409 and response.json()["code"] == "QUOTE_CUSTOMER_MISMATCH"
    with client.app.state.session_factory() as session:
        data = session.get(ObjectRow, (d, "synthetic", "facts")).data
        assert data["quote_customer_ref"] == "C-test" and data["remnant"]["status"] == "available"
        assert session.get(ObjectRow, (d, "synthetic", "synthetic-reservation")) is None
        assert session.get(ObjectRow, (d, "order_sheet", sheet["order_id"])).data == sheet
