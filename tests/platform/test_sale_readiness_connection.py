"""Synthetic IDs/evidence exercise production matching, C2, parent hook and stored refs."""
import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from glassflow.contracts.cutting import CutPlan, Placement, RemnantUpdate
from glassflow.core.domain_jobs import cutting_job, store_cutting, validate_cutting
from glassflow.core.errors import AppError
from glassflow.core.models import DatasetRow, JobRow, ObjectRow, RecordRow
from glassflow.core.snapshots import cutting_snapshot, sale_readiness_snapshot
from glassflow.core.uow import write_transaction
from glassflow.main import create_app
from glassflow.modules.cutting.conversion import snapshot_from_input, to_assignment
from glassflow.modules.cutting.geometry import validate_plan
from glassflow.modules.cutting.metrics import compute_metrics
from glassflow.modules.cutting.service import CuttingService
from glassflow.modules.platform.runs import enqueue_sale_readiness


class Context:
    def cancelled(self): return False
    def progress(self, *args): pass
    def remaining_seconds(self): return None


@pytest.fixture
def connection(tmp_path):
    with TestClient(create_app(tmp_path, testing=True)) as client:
        client.app.state.coordinator.stop()
        yield client.app.state.session_factory


def setup(factory, *, extra=220, maximum=150, prefix="changed-ids"):
    ds = prefix
    stock = [{"remnant_id": f"{prefix}-{i*17+3}", "material_id": "clear", "длина_мм": str(size),
              "ширина_мм": str(size), "возраст_дней": "10", "дефект": "0", "место": "Тест А"}
             for i, size in enumerate([110]*5+[extra])]
    materials = [{"material_id": "clear", "название": "Стекло прозрачное", "толщина_мм": "4",
                  "цена_нового_стекла_тг_за_м2": "5000", "закалённое": "0"}]
    orders = [{"part_id": prefix+"-part", "order_id": prefix+"-order", "material_id": "clear",
               "длина_мм": "100", "ширина_мм": "100", "премиум": "0", "тип_изделия": "полка"}]
    rows = {"stock": list(reversed(stock)), "materials": materials, "orders": orders}
    data = cutting_snapshot(ds, rows, {"profile": "quick", "minimum_free_remnants": 5})
    domain = snapshot_from_input(data)
    placements = [Placement(part_id=orders[0]["part_id"], remnant_id=stock[0]["remnant_id"], x_mm=5, y_mm=5, rot=0)]
    metrics, free = compute_metrics(domain, validate_plan(domain, [to_assignment(p) for p in placements]))
    baseline = CutPlan(dataset_id=ds, plan_id="initial", revision=0, status="validated", placements=placements,
                       metrics=metrics, free_original_remnant_ids=free, config=data.config,
                       search_status="feasible", stop_reason="original-stop", evidence={"original": "kept"})
    application = {"application": "furniture_insert", "material_ids": ["clear"],
                   "min_dimensions": {"length_mm": 100, "width_mm": 100},
                   "max_dimensions": {"length_mm": maximum, "width_mm": maximum}, "requires_cutting": True,
                   "dimensions_basis": "Synthetic test assumption", "activity": "Synthetic test furniture maker",
                   "source_url": "https://example.org/test-only", "checked_at": "2026-11-28"}
    buyers = [{"buyer_id": f"org-{n}", "name": f"Synthetic-{n}", "score": 80} for n in range(3)]
    evidence = [{"name": b["name"], "applications": [deepcopy(application)]} for b in buyers]
    with write_transaction(factory) as session:
        session.add(DatasetRow(id=ds, name="Synthetic connection regression", mode="workspace", fingerprint=ds,
                               source_hashes={}, row_counts={}))
        session.flush()
        for kind, records in rows.items():
            for n, record in enumerate(records):
                key = record[{"stock": "remnant_id", "materials": "material_id", "orders": "part_id"}[kind]]
                session.add(RecordRow(dataset_id=ds, kind=kind, public_id=key, source_row=n+2, data=record))
        CuttingService(session).register_dataset(ds, "workspace", domain)
        session.add(ObjectRow(dataset_id=ds, kind="buyer_registry", id="reviewed-test-registry", version=0,
                              data={"status": "verified", "buyers": buyers, "evidence": {"records": evidence}}))
        baseline = CuttingService(session).store_solver_plan(ds, baseline)
    return ds, baseline


def pending(factory, ds, baseline):
    with write_transaction(factory) as session:
        dto = enqueue_sale_readiness(session, ds, baseline.plan_id, baseline.revision, "reviewed-test-registry")
        job = session.get(JobRow, dto["job_id"])
        job.state = "running"
        snapshot = deepcopy(job.input)
    return snapshot


@pytest.mark.parametrize("extra,maximum,status,selected_other", [
    (220, 1000, "ready_unchanged", False), (220, 150, "ready_alternative", True),
    (90, 150, "tradeoff_available", False), (220, 105, "evidence_shortage", False),
])
def test_real_evidence_connection_preserves_baseline_and_selects_only_lossless(connection,
        extra, maximum, status, selected_other):
    ds, baseline = setup(connection, extra=extra, maximum=maximum)
    snapshot = pending(connection, ds, baseline)
    result = cutting_job(snapshot, Context())
    assert validate_cutting(snapshot, result)
    with write_transaction(connection) as session:
        store_cutting(session, ds, result)
        readiness = result["sale_readiness"]
        assert readiness["status"] == status
        assert readiness["baseline"]["stop_reason"] == "original-stop"
        assert readiness["baseline"]["evidence"]["original"] == "kept"
        assert result["baseline_plan_ref"] != result["selected_plan_ref"] if selected_other else (
            result["baseline_plan_ref"] == result["selected_plan_ref"])
        if status == "tradeoff_available":
            assert result["tradeoff_plan_ref"] and readiness["delta_area_mm2"] == -10000
        if status in {"ready_unchanged", "evidence_shortage"}:
            assert not readiness["search_performed"]


@pytest.mark.parametrize("change", ["registry", "reserve", "measurement"])
def test_parent_rejects_current_evidence_or_inventory_changes(connection, change):
    ds, baseline = setup(connection)
    snapshot = pending(connection, ds, baseline)
    result = cutting_job(snapshot, Context())
    with write_transaction(connection) as session:
        if change == "registry":
            row = session.get(ObjectRow, (ds, "buyer_registry", "reviewed-test-registry"))
            row.data = {**row.data, "note": "changed evidence, same public version ID"}
        else:
            from glassflow.contracts.cutting import ReserveRequest
            rid = snapshot["sale_context"]["eligible_original_ids"][-1]
            service = CuttingService(session)
            current = service.get_remnant(ds, rid)
            if change == "reserve":
                service.reserve(rid, ReserveRequest(dataset_id=ds, expected_version=current.version,
                    owner_context="other-manager", material_id="clear", dimensions={"length_mm": 10, "width_mm": 10}))
            else:
                service.update_remnant(rid, RemnantUpdate(dataset_id=ds, expected_version=current.version,
                    location_raw="Changed shelf"))
    with pytest.raises(AppError, match="Изменился"):
        with write_transaction(connection) as session:
            store_cutting(session, ds, result)
    with connection() as session:
        assert CuttingService(session).get_plan(ds, baseline.plan_id).metrics.covered_area_mm2 == 10000


def test_client_like_eligibility_tampering_is_not_parent_authority(connection):
    ds, baseline = setup(connection)
    snapshot = pending(connection, ds, baseline)
    result = cutting_job(snapshot, Context())
    bundle = json.loads(result["evidence"]["sale_readiness_bundle"])
    bundle["context"]["eligible_original_ids"] = ["invented"]
    result["evidence"]["sale_readiness_bundle"] = json.dumps(bundle)
    assert not validate_cutting(snapshot, result)
    with pytest.raises(AppError):
        with write_transaction(connection) as session:
            store_cutting(session, ds, result)
    # Raw baseline is permitted as an incumbent, but cannot bypass the final hook.
    result = cutting_job(snapshot, Context())
    result["evidence"].pop("sale_readiness_bundle")
    assert validate_cutting(snapshot, result)
    with pytest.raises(AppError, match="совместную"):
        with write_transaction(connection) as session:
            store_cutting(session, ds, result)


def test_forged_area_delta_cannot_promote_a_loss_and_all_writes_rollback(connection):
    from sqlalchemy import func, select

    from glassflow.modules.cutting.models import CutPlanRow
    ds, baseline = setup(connection, extra=90)
    snapshot = pending(connection, ds, baseline)
    result = cutting_job(snapshot, Context())
    bundle = json.loads(result["evidence"]["sale_readiness_bundle"])
    candidate = bundle["outcome"].pop("tradeoff")
    candidate["metrics"]["covered_area_mm2"] = 10000  # A child's numeric assertion is not geometry.
    bundle["outcome"].update(alternative=candidate, tradeoff=None, delta_area_mm2=0, status="ready_alternative")
    result["evidence"]["sale_readiness_bundle"] = json.dumps(bundle)
    with pytest.raises(AppError, match="Уступка"):
        with write_transaction(connection) as session:
            store_cutting(session, ds, result)
    with connection() as session:
        assert session.scalar(select(func.count()).select_from(CutPlanRow)) == 1


def test_match_set_is_derived_from_real_sources_and_new_ids(connection):
    ds, baseline = setup(connection, prefix="OTHER-109")
    with connection() as session:
        _, context = sale_readiness_snapshot(session, ds, "reviewed-test-registry", baseline.config)
    assert len(context["eligible_original_ids"]) == 5
    assert all(x.startswith("OTHER-109") for x in context["eligible_original_ids"])


def test_committed_plan_keeps_its_own_reservations_and_original_plan_ref(connection):
    from glassflow.contracts.cutting import CommitPlan
    ds, baseline = setup(connection, maximum=1000)
    with write_transaction(connection) as session:
        service = CuttingService(session)
        versions = {p.remnant_id: service.get_remnant(ds, p.remnant_id).version for p in baseline.placements}
        service.commit(baseline.plan_id, CommitPlan(dataset_id=ds, plan_revision=baseline.revision,
                                                  expected_remnant_versions=versions))
        baseline = service.get_plan(ds, baseline.plan_id)
    snapshot = pending(connection, ds, baseline)
    result = cutting_job(snapshot, Context())
    assert validate_cutting(snapshot, result)
    with write_transaction(connection) as session:
        store_cutting(session, ds, result)
        assert result["selected_plan_ref"] == {"plan_id": baseline.plan_id, "revision": baseline.revision}
        assert result["sale_readiness"]["status"] == "ready_unchanged"


def test_real_spawn_queue_selects_verified_plan_and_cards_follow_it(connection):
    import time

    from glassflow.contracts.crm import CardsRequest
    from glassflow.core.composition import domain_services
    from glassflow.core.jobs import Coordinator
    from glassflow.modules.sales.service import generate_cards
    ds, baseline = setup(connection)
    services = domain_services()
    coordinator = Coordinator(connection, services.job_handlers, result_hooks=services.result_hooks)
    coordinator.start()
    try:
        with write_transaction(connection) as session:
            job = enqueue_sale_readiness(session, ds, baseline.plan_id, baseline.revision, "reviewed-test-registry")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with connection() as session:
                row = session.get(JobRow, job["job_id"])
                state, result = row.state, deepcopy(row.result)
            if state in {"completed", "failed"}:
                break
            time.sleep(.05)
        assert state == "completed", (state, result)
        assert result["sale_readiness"]["status"] == "ready_alternative"
        assert "sale_readiness_bundle" not in result["evidence"]
        with write_transaction(connection) as session:
            cards = generate_cards(session, CardsRequest(dataset_id=ds,
                plan_id=result["selected_plan_ref"]["plan_id"], plan_revision=result["selected_plan_ref"]["revision"],
                buyer_registry_version="reviewed-test-registry"), services, "synthetic-connection")
            assert len(cards["cards"]) == 5
            assert all(c["plan_id"] == result["selected_plan_ref"]["plan_id"] and len(c["buyer_matches"]) >= 3
                       for c in cards["cards"])
    finally:
        coordinator.stop()


def test_batch_review_metadata_is_parent_checked_and_stored_in_shared_transaction(connection):
    import base64
    import csv
    import io
    from pathlib import Path

    from sqlalchemy import select

    from glassflow.core.domain_jobs import assistant_job, store_assistant
    from glassflow.modules.intelligence.models import IntelligenceReviewRow
    from glassflow.modules.platform.checkpoints import validate_assistant_checkpoint
    ds, _ = setup(connection)
    pack = Path(__file__).resolve().parents[2] / "inputs/PACK_for_teams"
    material_bytes = (pack / "1_ostatki/materials.csv").read_bytes()
    snapshot = {"dataset_id": ds, "ai_profile": "local_limited", "ai_settings": {},
        "materials": list(csv.DictReader(io.StringIO(material_bytes.decode("utf-8-sig")))),
        "materials_bytes_b64": base64.b64encode(material_bytes).decode(),
        "kb_bytes_b64": base64.b64encode((pack / "2_assistant_crm/ksm_knowledge_base.json").read_bytes()).decode(),
        "questions": [{"id": "new-installation-id", "question": "Выполняете ли монтаж?"}]}
    class Accepted(Context):
        private_config = {}
        payloads = []
        def checkpoint(self, row_id, fingerprint, payload):
            assert validate_assistant_checkpoint(snapshot, row_id, fingerprint, payload)
            self.payloads.append((row_id, fingerprint, deepcopy(payload)))
    context = Accepted()
    result = assistant_job(snapshot, context)
    row_id, fingerprint, payload = context.payloads[0]
    assert payload["provenance"]["review_reasons"]["correct_policy"]
    bad = deepcopy(payload)
    bad["provenance"]["review_reasons"] = {"missing_parameter": ["invented"]}
    assert not validate_assistant_checkpoint(snapshot, row_id, fingerprint, bad)
    bad = deepcopy(payload)
    bad["provenance"]["review_reasons"]["provider_error"] = ["invented"]
    assert not validate_assistant_checkpoint(snapshot, row_id, fingerprint, bad)
    with pytest.raises(RuntimeError):
        with write_transaction(connection) as session:
            store_assistant(session, ds, result)
            raise RuntimeError("forced shared transaction rollback")
    with connection() as session:
        assert not list(session.scalars(select(IntelligenceReviewRow)))
    with write_transaction(connection) as session:
        store_assistant(session, ds, result)
    with connection() as session:
        rows = list(session.scalars(select(IntelligenceReviewRow)))
        assert len(rows) == 1 and rows[0].category == "correct_policy"
