"""U04 platform tests. Synthetic C2/C3 adapters are not real geometry/pricing acceptance."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from glassflow.contracts.baskets import BasketFacts, BasketReservation
from glassflow.contracts.intelligence import QuoteRequest
from glassflow.core.errors import AppError
from glassflow.core.jobs import Handler
from glassflow.core.models import JobRow, ObjectRow
from glassflow.core.uow import canonical_hash, write_transaction
from glassflow.main import create_app


def workspace(client, imported):
    return client.post(f"/api/v1/datasets/{imported['dataset_id']}/working-copy", json={},
                        headers={"Idempotency-Key": "basket-workspace"}).json()["dataset_id"]


def draft_lines(dataset_id):
    return [dict(line_id=f"line-{i}", text=f"Synthetic item{i}", request=dict(
        dataset_id=dataset_id, catalog_product_id=f"synthetic-{i}", customer_id="C-basket", kb_version="synthetic-kb",
        quantity=2 if i == 1 else 1, dimensions=dict(length_mm=450+i, width_mm=370) if i < 3 else None,
        processing=dict(kind="euro_edge", sides="selected", selected_sides=["left", "bottom"]) if i == 1 else dict(kind="none"),
    )) for i in range(1, 4)]


def create_basket(client, d, key="basket"):
    response = client.post("/api/v1/baskets", json=dict(dataset_id=d, customer_ref="C-basket",
                        request_text="Synthetic: two glasses and a catalog item", lines=draft_lines(d)),
                        headers={"Idempotency-Key": key})
    assert response.status_code == 200, response.text
    return response.json()


def command(client, basket, action, key=None, **extra):
    return client.post(f"/api/v1/baskets/{basket['basket_id']}/{action}", json=dict(
        dataset_id=basket["dataset_id"], expected_version=basket["version"], operator="synthetic-manager", **extra),
        headers={"Idempotency-Key": key or f"{action}-{basket['version']}"})


class SyntheticBasketSource:
    """DB-backed stub for atomic C2/C3 seams only. No real nesting engine is represented."""
    fail_after_first_write = False
    corrupt_after_reserve = False
    reserve_calls = 0

    def capture(self, session, basket, binding):
        row = session.get(ObjectRow, (basket.dataset_id, "synthetic_basket", basket.basket_id))
        value = BasketFacts.model_validate(row.data)
        stock = session.get(ObjectRow, (basket.dataset_id, "synthetic_basket", "shared-piece"))
        if value.stock:
            value.stock.remnant_versions = {"shared-piece": stock.version}
            value.stock.validated = stock.data.get("owner") in {None, basket.basket_id}
        return value

    def reserve(self, session, basket):
        self.reserve_calls += 1
        piece = session.get(ObjectRow, (basket.dataset_id, "synthetic_basket", "shared-piece"))
        if piece.data.get("owner") is not None or piece.version != basket.facts.stock.remnant_versions["shared-piece"]:
            raise AppError(409, "SYNTHETIC_BUNDLE_CONFLICT", "Synthetic joint conflict")
        piece.data, piece.version = {"owner": basket.basket_id}, piece.version+1
        session.flush()
        if self.fail_after_first_write:
            raise AppError(409, "SYNTHETIC_SECOND_LINE_FAILURE", "Synthetic failure after first tentative write")
        if self.corrupt_after_reserve:
            row = session.get(ObjectRow, (basket.dataset_id, "synthetic_basket", basket.basket_id))
            value = BasketFacts.model_validate(row.data)
            value.lines[0].quote.total_tg = "999999"
            row.data = value.model_dump(mode="json")
        ref = BasketReservation(dataset_id=basket.dataset_id, reservation_id="bundle-"+basket.basket_id,
            basket_id=basket.basket_id, basket_revision=basket.revision, selection_ref=basket.facts.stock.selection_ref,
            selection_version=basket.facts.stock.selection_version, remnant_versions={"shared-piece": piece.version}, state="active")
        session.add(ObjectRow(dataset_id=basket.dataset_id, kind="synthetic_reservation", id=ref.reservation_id,
                              version=0, data=ref.model_dump(mode="json")))
        return ref

    def reservation(self, session, dataset_id, reservation_id):
        return BasketReservation.model_validate(session.get(ObjectRow, (dataset_id, "synthetic_reservation", reservation_id)).data)

    def release(self, session, reservation):
        piece = session.get(ObjectRow, (reservation.dataset_id, "synthetic_basket", "shared-piece"))
        assert piece.data["owner"] == reservation.basket_id
        piece.version, piece.data = piece.version+1, {"owner": None}
        released = reservation.model_copy(update={"state": "released", "remnant_versions": {"shared-piece": piece.version}})
        session.get(ObjectRow, (reservation.dataset_id, "synthetic_reservation", reservation.reservation_id)).data = released.model_dump(mode="json")
        return released


def seed_facts(client, basket, *, partial=False, catalog_only=False):
    d, bid = basket["dataset_id"], basket["basket_id"]
    lines = [dict(line_id=line["line_id"], kind="catalog" if catalog_only or i == 2 else "glass",
        quote=dict(dataset_id=d, quote_id="quote-"+line["line_id"], revision=1, status="ready",
                   components=[], total_tg=str((i+1)*1000), preliminary=False,
                   material_mapping_status="confirmed", material_id="clear-6" if i < 2 and not catalog_only else None),
        quote_customer_ref="C-basket", source_request_hash=canonical_hash(QuoteRequest.model_validate(line["request"]).model_dump(mode="json")),
        compatibility="confirmed" if i == 2 else "not_required") for i, line in enumerate(basket["lines"])]
    if partial:
        lines[-1]["quote"]["total_tg"] = None
        lines[-1]["compatibility"] = "needs_review"
    facts = BasketFacts(dataset_id=d, basket_id=bid, input_hash=basket["input_hash"], lines=lines,
        stock=None if catalog_only else dict(dataset_id=d, basket_id=bid, input_hash=basket["input_hash"],
            selection_ref="selection-"+bid, selection_version=1, line_ids=[line["line_id"] for line in lines[:2]],
            remnant_versions={"shared-piece": 0}, validated=True, validation_ref="synthetic-joint-valid",
            planned_area_mm2=500000, planned_material_value_tg="4000"))
    with write_transaction(client.app.state.session_factory) as session:
        session.add(ObjectRow(dataset_id=d, kind="synthetic_basket", id=bid, version=0, data=facts.model_dump(mode="json")))
        if session.get(ObjectRow, (d, "synthetic_basket", "shared-piece")) is None:
            session.add(ObjectRow(dataset_id=d, kind="synthetic_basket", id="shared-piece", version=0, data={"owner": None}))
    return facts


def bind(client, basket, facts):
    response = command(client, basket, "bind", lines=[dict(line_id=line.line_id, quote_id=line.quote.quote_id, quote_revision=line.quote.revision) for line in facts.lines],
                       selection_ref=facts.stock.selection_ref if facts.stock else None,
                       selection_version=facts.stock.selection_version if facts.stock else None)
    assert response.status_code == 200, response.text
    return response.json()


def prepared(client, imported, services, key="basket", **options):
    d = workspace(client, imported)
    services.basket_source = SyntheticBasketSource()
    basket = create_basket(client, d, key)
    return bind(client, basket, seed_facts(client, basket, **options))


def test_whole_basket_confirm_reserve_history_restart_and_canonical_quantity(client, imported, services):
    basket = prepared(client, imported, services)
    assert basket["total_tg"] == "6000"  # NOT multiplying first line quantity2 a second time.
    assert basket["lines"][0]["request"]["quantity"] == 2
    assert basket["lines"][0]["request"]["processing"]["selected_sides"] == ["left", "bottom"]
    basket = command(client, basket, "confirm").json()
    before = basket
    basket = command(client, basket, "reserve", key="whole-reserve").json()
    assert basket["state"] == "reserved" and services.basket_source.reserve_calls == 1
    assert command(client, before, "reserve", key="whole-reserve").json() == basket
    assert command(client, basket, "reserve", key="different-key-same-bundle").json() == basket
    assert services.basket_source.reserve_calls == 1
    assert command(client, basket, "lines", lines=draft_lines(basket["dataset_id"])).status_code == 409
    basket = command(client, basket, "warehouse-check", note="Synthetic human inspection all lines").json()
    basket = command(client, basket, "handover").json()
    with TestClient(create_app(client.app.state.data_dir, services, testing=True)) as restarted:
        url = f"/api/v1/baskets/{basket['basket_id']}"
        assert restarted.get(url, params={"dataset_id": basket["dataset_id"]}).json() == basket
        events = restarted.get(url+"/history", params={"dataset_id": basket["dataset_id"]}).json()
        assert events[-1]["basket"] == basket
        assert [e["action"] for e in events].count("basket.reserve") == 1


def test_unknown_rate_or_compatibility_blocks_entire_basket(client, imported, services):
    basket = prepared(client, imported, services, partial=True)
    assert basket["state"] == "needs_review" and basket["total_tg"] is None
    assert basket["known_subtotal_tg"] == "3000"
    assert command(client, basket, "confirm").status_code == 409
    assert command(client, basket, "reserve").status_code == 409
    assert services.basket_source.reserve_calls == 0


@pytest.mark.parametrize("failure", ["fail_after_first_write", "corrupt_after_reserve"])
def test_partial_reserve_and_post_reserve_changed_quote_roll_back_everything(client, imported, services, failure):
    basket = command(client, prepared(client, imported, services), "confirm").json()
    setattr(services.basket_source, failure, True)
    assert command(client, basket, "reserve").status_code == 409
    with client.app.state.session_factory() as session:
        piece = session.get(ObjectRow, (basket["dataset_id"], "synthetic_basket", "shared-piece"))
        assert piece.version == 0 and piece.data["owner"] is None
        assert session.get(ObjectRow, (basket["dataset_id"], "synthetic_reservation", "bundle-"+basket["basket_id"])) is None
        assert session.get(ObjectRow, (basket["dataset_id"], "basket", basket["basket_id"])).data == basket


def test_two_baskets_compete_for_same_piece_and_loser_is_stale(client, imported, services):
    first = prepared(client, imported, services, "one")
    second = create_basket(client, first["dataset_id"], "two")
    second = bind(client, second, seed_facts(client, second))
    first, second = [command(client, item, "confirm").json() for item in (first, second)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda item: command(client, item, "reserve", key=item["basket_id"]), (first, second)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    loser = second if responses[0].status_code == 200 else first
    stale = client.get(f"/api/v1/baskets/{loser['basket_id']}", params={"dataset_id": loser["dataset_id"]}).json()
    assert stale["state"] == "stale" and stale["total_tg"] is None


@pytest.mark.parametrize("change", ["owner", "request_hash", "drop_line", "stock_subset"])
def test_canonical_scope_and_owner_mismatch_never_confirm(client, imported, services, change):
    basket = prepared(client, imported, services)
    with write_transaction(client.app.state.session_factory) as session:
        row = session.get(ObjectRow, (basket["dataset_id"], "synthetic_basket", basket["basket_id"]))
        facts = BasketFacts.model_validate(row.data)
        if change == "owner":
            facts.lines[0].quote_customer_ref = "another-customer"
        elif change == "request_hash":
            facts.lines[0].source_request_hash = "wrong"
        elif change == "drop_line":
            facts.lines.pop()
        else:
            facts.stock.line_ids.pop()
        row.data = facts.model_dump(mode="json")
    response = command(client, basket, "confirm")
    assert response.status_code == 409
    assert services.basket_source.reserve_calls == 0


def test_catalog_only_does_not_claim_material_reserve_and_absent_services_fail_explicitly(client, imported, services):
    d = workspace(client, imported)
    basket = create_basket(client, d)
    assert command(client, basket, "parse").status_code == 503
    assert command(client, basket, "bind", lines=[dict(line_id=line["line_id"]) for line in basket["lines"]]).status_code == 503
    services.basket_source = SyntheticBasketSource()
    basket = bind(client, basket, seed_facts(client, basket, catalog_only=True))
    basket = command(client, basket, "confirm").json()
    basket = command(client, basket, "reserve").json()
    assert basket["reservation"] is None and services.basket_source.reserve_calls == 0
    basket = command(client, basket, "cancel").json()
    assert basket["state"] == "cancelled"


def test_parse_result_cannot_overwrite_edits_or_cross_baskets(client, imported, services):
    d = workspace(client, imported)
    basket = create_basket(client, d)
    with write_transaction(client.app.state.session_factory) as session:
        job = JobRow(dataset_id=d, kind="basket.parse", state="completed", input=dict(
            dataset_id=d, basket_id=basket["basket_id"], basket_version=0, input_hash=basket["input_hash"]),
            result=dict(dataset_id=d, basket_id=basket["basket_id"], basket_version=0,
                        input_hash=basket["input_hash"], lines=basket["lines"], warnings=[]))
        session.add(job)
        session.flush()
        job_id = job.id
    # Explicit apply of a completed C3 parse is supported, not automatic confirmation.
    applied = command(client, basket, "apply-parse", job_id=job_id)
    assert applied.status_code == 200 and applied.json()["state"] == "draft"
    assert command(client, applied.json(), "apply-parse", job_id=job_id).status_code == 409
    other = create_basket(client, d, "other")
    assert command(client, other, "apply-parse", job_id=job_id).status_code == 409


def synthetic_parser(snapshot, context):
    """Explicit synthetic worker proving job protocol only."""
    context.progress("synthetic_parse", 1, 1)
    return {k: snapshot[k] for k in ("dataset_id", "basket_id", "basket_version", "input_hash")} | {
        "lines": snapshot["existing_lines"], "warnings": ["Explicit synthetic parser result"]}


def test_parser_uses_durable_queue_and_only_pinned_kb_no_crm(client, imported, services):
    import time
    basket = create_basket(client, workspace(client, imported))
    client.app.state.coordinator.handlers["basket.parse"] = Handler(synthetic_parser, lane="network")
    response = command(client, basket, "parse", key="parse")
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    with client.app.state.session_factory() as session:
        snapshot = session.get(JobRow, job_id).input
        assert snapshot["kb_version"] and snapshot["kb"]
        assert "applications" not in snapshot and "api_key" not in str(snapshot)
    deadline = time.monotonic()+15
    while time.monotonic() < deadline:
        view = client.get(f"/api/v1/jobs/{job_id}").json()
        if view["state"] in {"completed", "failed"}:
            break
        time.sleep(0.05)
    assert view["state"] == "completed", view
    result = command(client, basket, "apply-parse", job_id=job_id)
    assert result.status_code == 200 and result.json()["state"] == "needs_review"


def test_adapter_cannot_mutate_pinned_basket_to_hide_changed_quote(client, imported, services):
    class AliasingSource(SyntheticBasketSource):
        def reserve(self, session, basket):
            ref = super().reserve(session, basket)
            basket.facts.lines[0].quote.total_tg = "999999"
            row = session.get(ObjectRow, (basket.dataset_id, "synthetic_basket", basket.basket_id))
            facts = BasketFacts.model_validate(row.data)
            facts.lines[0].quote.total_tg = "999999"
            row.data = facts.model_dump(mode="json")
            return ref

    basket = command(client, prepared(client, imported, services), "confirm").json()
    services.basket_source = AliasingSource()
    response = command(client, basket, "reserve")
    assert response.status_code == 409 and response.json()["code"] == "BASKET_RESERVATION_FACTS"
    with client.app.state.session_factory() as session:
        assert session.get(ObjectRow, (basket["dataset_id"], "basket", basket["basket_id"])).data == basket
        assert session.get(ObjectRow, (basket["dataset_id"], "synthetic_basket", "shared-piece")).data["owner"] is None


def test_rebinding_after_release_discards_old_reservation_reference(client, imported, services):
    basket = command(client, prepared(client, imported, services), "confirm").json()
    basket = command(client, basket, "reserve").json()
    released = command(client, basket, "release").json()
    assert released["reservation"]["state"] == "released"
    facts = BasketFacts.model_validate(released["facts"])
    rebound = bind(client, released, facts)
    assert rebound["state"] == "ready" and rebound["reservation"] is None
    assert rebound["revision"] == released["revision"] + 1


@pytest.mark.parametrize("legacy", [False, True])
def test_parse_warning_survives_quote_binding_until_explicit_line_review(client, imported, services, legacy):
    d = workspace(client, imported)
    services.basket_source = SyntheticBasketSource()
    basket = create_basket(client, d)
    with write_transaction(client.app.state.session_factory) as session:
        job = JobRow(dataset_id=d, kind="basket.parse", state="completed", input=dict(
            dataset_id=d, basket_id=basket["basket_id"], basket_version=0, input_hash=basket["input_hash"]),
            result=dict(dataset_id=d, basket_id=basket["basket_id"], basket_version=0, input_hash=basket["input_hash"],
                        lines=basket["lines"], warnings=["Synthetic quantity needs human clarification"]))
        session.add(job)
        session.flush()
        job_id = job.id
    applied = command(client, basket, "apply-parse", job_id=job_id).json()
    if legacy:
        with write_transaction(client.app.state.session_factory) as session:
            row = session.get(ObjectRow, (d, "basket", basket["basket_id"]))
            row.data = {key: value for key, value in row.data.items() if key != "review_warnings"}
    facts = seed_facts(client, applied)
    bound = bind(client, applied, facts)
    assert bound["state"] == "needs_review" and bound["total_tg"] is None
    assert command(client, bound, "confirm").status_code == 409
    assert command(client, bound, "lines", lines=bound["lines"], key="no-review-note").status_code == 422
    reviewed = command(client, bound, "lines", lines=bound["lines"], note="Manager explicitly checked quantity").json()
    ready = bind(client, reviewed, facts)
    assert ready["state"] == "ready" and ready["total_tg"] == "6000"
