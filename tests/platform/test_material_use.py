"""U06 synthetic transactional C2 seam tests, not real material execution acceptance."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from test_baskets import bind as basket_bind
from test_baskets import command as basket_command
from test_baskets import create_basket, prepared, seed_facts
from test_orders import bound as order_bound
from test_orders import command as order_command
from test_orders import setup as order_setup

from glassflow.contracts.material_use import MaterialUseAssessment, MaterialUseReceipt
from glassflow.core.errors import AppError
from glassflow.core.models import MaterialUseRow, ObjectRow, now, uid
from glassflow.core.uow import write_transaction
from glassflow.main import create_app


class SyntheticUseSource:
    """Pretend canonical C2 execution, persisted with caller UoW. No actual valuation engine."""
    calls = 0
    fault = None
    event_override = None

    def assess(self, session, scope, execution_ref, execution_version):
        if execution_ref != "execution-"+scope.subject_id or execution_version != 1:
            raise AppError(409, "SYNTHETIC_EXECUTION_STALE", "Synthetic execution revision mismatch")
        if scope.subject_type == "basket":
            reservation = session.get(ObjectRow, (scope.dataset_id, "synthetic_reservation", scope.reservation_id))
            piece = session.get(ObjectRow, (scope.dataset_id, "synthetic_basket", "shared-piece"))
            if (reservation.data["state"] != "active" or reservation.data["basket_id"] != scope.subject_id
                    or scope.remnant_versions != {"shared-piece": piece.version}):
                raise AppError(409, "SYNTHETIC_RESERVATION_STALE", "Synthetic reservation stale")
        else:
            reservation = session.get(ObjectRow, (scope.dataset_id, "synthetic", scope.reservation_id))
            if reservation.data["state"] != "active" or reservation.data["order_id"] != scope.subject_id:
                raise AppError(409, "SYNTHETIC_RESERVATION_STALE", "Synthetic reservation stale")
        assessment = MaterialUseAssessment(scope=scope, execution_ref=execution_ref, execution_version=1,
            planned_area_mm2=500000, actual_area_mm2=450000, planned_material_value_tg="4000",
            actual_material_value_tg="3600", validation_ref="explicit-synthetic-execution-validation",
            material_price_version="synthetic-material-price1")
        if self.fault == "scope":
            assessment.scope = scope.model_copy(update={"subject_id": "another-subject"})
        elif self.fault == "plan":
            assessment.planned_area_mm2 += 1
        return assessment

    def confirm(self, session, assessment, confirmation_id, operator, note):
        self.calls += 1
        scope = assessment.scope
        post = {rid: version+1 for rid, version in scope.remnant_versions.items()}
        if scope.subject_type == "basket":
            ref = session.get(ObjectRow, (scope.dataset_id, "synthetic_reservation", scope.reservation_id))
            ref.data = {**ref.data, "state": "consumed", "remnant_versions": post}
            piece = session.get(ObjectRow, (scope.dataset_id, "synthetic_basket", "shared-piece"))
            # This fixture has no geometry. Clearing ownership permits event-collision fault injection below.
            piece.version, piece.data = post["shared-piece"], {"owner": None}
        else:
            ref = session.get(ObjectRow, (scope.dataset_id, "synthetic", scope.reservation_id))
            ref.data = {**ref.data, "state": "consumed"}
            row = session.get(ObjectRow, (scope.dataset_id, "synthetic", "facts"))
            row.data = {**row.data, "remnant": {**row.data["remnant"], "status": "consumed", "version": next(iter(post.values()))}}
        session.flush()
        result = MaterialUseReceipt(assessment=assessment, confirmation_id=confirmation_id,
            source_event_ref=self.event_override or "event-"+scope.subject_id, reservation_state="consumed",
            post_remnant_versions=post, confirmed_at=now()).model_dump(mode="json")
        if self.fault == "receipt_scope":
            result["assessment"]["actual_area_mm2"] += 1
        elif self.fault == "token":
            result["confirmation_id"] = "wrong-token"
        elif self.fault == "versions":
            result["post_remnant_versions"] = scope.remnant_versions
        elif self.fault == "timestamp":
            result["confirmed_at"] = "2026-11-28T09:00:00"
        return result


def handed_basket(client, imported, services):
    basket = prepared(client, imported, services)
    return handover(client, basket)


def handover(client, basket):
    for action in ("confirm", "reserve", "warehouse-check", "handover"):
        response = basket_command(client, basket, action, note="Synthetic all-lines warehouse inspection")
        assert response.status_code == 200, response.text
        basket = response.json()
    return basket


def body_for(subject, kind="basket"):
    return dict(dataset_id=subject["dataset_id"], subject_type=kind,
        subject_id=subject["basket_id"] if kind == "basket" else subject["order_id"],
        expected_version=subject["version"], execution_ref="execution-"+(subject["basket_id"] if kind == "basket" else subject["order_id"]),
        execution_version=1, operator="synthetic-warehouse-operator", note="Synthetic human confirmation",
        discrepancy_reason="Synthetic: confirmed actual execution differs from the planning estimate")


def post(client, body, key="use"):
    return client.post("/api/v1/material-use", json=body, headers={"Idempotency-Key": key})


def summary(client, d):
    return client.get("/api/v1/material-use/summary", params={"dataset_id": d}).json()


def test_confirm_preview_reason_semantic_replay_history_and_restart(client, imported, services):
    basket = handed_basket(client, imported, services)
    services.material_use = SyntheticUseSource()
    body = body_for(basket)
    preview = client.post("/api/v1/material-use/preview", json=body)
    assert preview.status_code == 200 and preview.json()["actual_material_value_tg"] == "3600"
    assert summary(client, basket["dataset_id"])["confirmation_count"] == 0
    assert post(client, {**body, "discrepancy_reason": ""}, "no-reason").status_code == 422
    assert services.material_use.calls == 0
    result = post(client, body)
    assert result.status_code == 200, result.text
    record = result.json()
    assert post(client, body).json() == record
    assert post(client, {**body, "operator": "another-operator"}, "different-key").json() == record
    assert services.material_use.calls == 1
    values = summary(client, basket["dataset_id"])
    assert values["planned_material_value_tg"] == "4000" and values["actual_material_value_tg"] == "3600"
    assert values["planned_area_mm2"] == 500000 and values["actual_area_mm2"] == 450000
    assert values["confirmation_count"] == 1 and values["usage_ids"] == [record["usage_id"]]
    assert "profit" not in values and "revenue" not in values
    assert post(client, {**body, "execution_version": 2}, "recount").status_code == 409
    url, params = f"/api/v1/baskets/{basket['basket_id']}", {"dataset_id": basket["dataset_id"]}
    completed = client.get(url, params=params).json()
    assert completed["state"] == "completed" and completed["reservation"]["state"] == "consumed"
    assert completed["material_use_id"] == record["usage_id"]
    assert client.get(url+"/history", params=params).json()[-1]["action"] == "basket.material_use"
    with TestClient(create_app(client.app.state.data_dir, services, testing=True)) as restarted:
        assert restarted.get(url, params=params).json() == completed
        assert post(restarted, body, "retry-after-restart").json() == record
        assert services.material_use.calls == 1


def test_concurrent_confirmation_with_distinct_keys_consumes_once(client, imported, services):
    basket = handed_basket(client, imported, services)
    services.material_use = SyntheticUseSource()
    body = body_for(basket)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda key: post(client, body, key), ("concurrent1", "concurrent2")))
    assert all(r.status_code == 200 for r in results)
    assert results[0].json() == results[1].json() and services.material_use.calls == 1
    assert summary(client, basket["dataset_id"])["confirmation_count"] == 1


@pytest.mark.parametrize("fault", ["scope", "plan", "receipt_scope", "token", "versions", "timestamp"])
def test_invalid_assessment_or_receipt_rolls_back_c2_and_ledger(client, imported, services, fault):
    basket = handed_basket(client, imported, services)
    services.material_use = SyntheticUseSource()
    services.material_use.fault = fault
    response = post(client, body_for(basket))
    assert response.status_code == 409, response.text
    with client.app.state.session_factory() as session:
        piece = session.get(ObjectRow, (basket["dataset_id"], "synthetic_basket", "shared-piece"))
        assert piece.version == basket["reservation"]["remnant_versions"]["shared-piece"]
        assert piece.data["owner"] == basket["basket_id"]
        assert not list(session.scalars(select(MaterialUseRow)))
        assert session.get(ObjectRow, (basket["dataset_id"], "basket", basket["basket_id"])).data == basket
    services.material_use.fault = None
    assert post(client, body_for(basket)).status_code == 200


def test_reserve_cancel_and_unconnected_source_never_count_as_actual_use(client, imported, services):
    basket = prepared(client, imported, services)
    assert post(client, body_for(basket)).status_code == 409
    basket = basket_command(client, basket, "confirm").json()
    basket = basket_command(client, basket, "reserve").json()
    assert summary(client, basket["dataset_id"])["actual_material_value_tg"] == "0"
    assert post(client, body_for(basket)).status_code == 409
    cancelled = basket_command(client, basket, "cancel").json()
    assert post(client, body_for(cancelled)).status_code == 409
    assert summary(client, basket["dataset_id"])["confirmation_count"] == 0
    other = create_basket(client, basket["dataset_id"], "other-use")
    other = basket_bind(client, other, seed_facts(client, other))
    other = handover(client, other)
    assert post(client, body_for(other)).status_code == 503
    assert summary(client, basket["dataset_id"])["confirmation_count"] == 0


def test_sql_ledger_is_immutable_and_source_event_cannot_be_reused(client, imported, services):
    first = handed_basket(client, imported, services)
    services.material_use = SyntheticUseSource()
    record = post(client, body_for(first)).json()
    for sql in ("UPDATE material_usage SET data='{}'", "DELETE FROM material_usage"):
        with pytest.raises(IntegrityError):
            with write_transaction(client.app.state.session_factory) as session:
                session.execute(text(sql))
    second = create_basket(client, first["dataset_id"], "second-event")
    second = handover(client, basket_bind(client, second, seed_facts(client, second)))
    # Deliberately faulty adapter offers a previously used event for another subject.
    services.material_use.event_override = record["receipt"]["source_event_ref"]
    response = post(client, body_for(second), "duplicate-source-event")
    assert response.status_code == 409 and response.json()["code"] == "MATERIAL_EVENT_ALREADY_USED"
    with client.app.state.session_factory() as session:
        assert session.get(ObjectRow, (second["dataset_id"], "synthetic_basket", "shared-piece")).data["owner"] == second["basket_id"]
    assert summary(client, first["dataset_id"])["confirmation_count"] == 1


def test_single_order_uses_same_ledger_and_completed_cannot_reconsume(client, imported, services):
    d = order_setup(client, imported, services)
    order = order_bound(client, d, "single-use")
    for action in ("confirm", "reserve", "warehouse-check", "handover"):
        result = order_command(client, order, action, note="Synthetic human warehouse check")
        assert result.status_code == 200, result.text
        order = result.json()
    services.material_use = SyntheticUseSource()
    record = post(client, body_for(order, "order")).json()
    saved = client.get(f"/api/v1/order-sheets/{order['order_id']}", params={"dataset_id": d}).json()
    assert saved["lifecycle"] == "completed" and saved["material_use_id"] == record["usage_id"]
    assert saved["offer"] is None and saved["warehouse_task"] is None
    assert order_command(client, saved, "reserve", key="cannot-reserve-completed").status_code == 409
    assert post(client, body_for(saved, "order"), "same-use-new-key").json() == record
    assert services.material_use.calls == 1


def test_unique_constraints_guard_other_writers_too(client, imported, services):
    basket = handed_basket(client, imported, services)
    services.material_use = SyntheticUseSource()
    record = post(client, body_for(basket)).json()
    with client.app.state.session_factory() as session:
        row = session.get(MaterialUseRow, record["usage_id"])
        original = {column.name: getattr(row, column.name) for column in MaterialUseRow.__table__.columns}
    for conflict in ("subject_id", "reservation_id", "source_event_ref"):
        values = {**original, "id": uid(), "subject_id": uid(), "reservation_id": uid(), "source_event_ref": uid()}
        values[conflict] = original[conflict]
        with pytest.raises(IntegrityError):
            with write_transaction(client.app.state.session_factory) as session:
                session.add(MaterialUseRow(**values))
                session.flush()
    assert summary(client, basket["dataset_id"])["confirmation_count"] == 1


def test_browser_cannot_supply_values_and_records_are_dataset_scoped(client, imported, services):
    basket = handed_basket(client, imported, services)
    services.material_use = SyntheticUseSource()
    body = body_for(basket)
    forged = post(client, {**body, "actual_material_value_tg": "0", "actual_area_mm2": 0})
    assert forged.status_code == 422 and services.material_use.calls == 0
    record = post(client, body).json()
    other = client.post(f"/api/v1/datasets/{imported['dataset_id']}/working-copy", json={},
                        headers={"Idempotency-Key": "another-usage-scope"}).json()["dataset_id"]
    assert client.get(f"/api/v1/material-use/{record['usage_id']}", params={"dataset_id": other}).status_code == 404
    assert summary(client, other)["confirmation_count"] == 0
    assert post(client, {**body, "dataset_id": other}, "wrong-dataset").status_code == 404


def test_adapter_cannot_mutate_approved_assessment_and_hide_discrepancy(client, imported, services):
    class AliasingUse(SyntheticUseSource):
        def assess(self, *args):
            value = super().assess(*args)
            value.actual_area_mm2, value.actual_material_value_tg = value.planned_area_mm2, value.planned_material_value_tg
            return value

        def confirm(self, session, assessment, confirmation_id, operator, note):
            assessment.actual_area_mm2 -= 1
            assessment.actual_material_value_tg = "3999"
            return super().confirm(session, assessment, confirmation_id, operator, note)

    basket = handed_basket(client, imported, services)
    services.material_use = AliasingUse()
    response = post(client, {**body_for(basket), "discrepancy_reason": ""})
    assert response.status_code == 409 and response.json()["code"] == "MATERIAL_RECEIPT_MISMATCH"
    assert summary(client, basket["dataset_id"])["confirmation_count"] == 0
