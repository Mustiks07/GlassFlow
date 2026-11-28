"""Fault-injected protocol tests plus real C2/C3/full-export opt-in budget acceptance."""

import base64
import csv
import io
import time
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from glassflow.core.jobs import Coordinator, Handler, enqueue
from glassflow.core.models import AuditRow, JobRow, ObjectRow
from glassflow.core.uow import write_transaction
from glassflow.modules.platform.budgets import create_budget, utc_now
from glassflow.modules.platform.checkpoints import row_fingerprint, validate_assistant_checkpoint

ROOT = Path(__file__).resolve().parents[2]


def synthetic_row_validator(snapshot, row_id, fingerprint, payload):
    return fingerprint == row_fingerprint(snapshot, row_id) and payload["row"] == {
        "answer": "synthetic:" + row_id
    }


def synthetic_checkpoint_worker(snapshot, context):
    accepted = {r["row_id"]: r for r in snapshot.get("accepted_rows", [])}
    fresh = []
    for index, q in enumerate(snapshot["questions"]):
        if q["id"] in accepted:
            continue
        context.checkpoint(
            q["id"],
            row_fingerprint(snapshot, q["id"]),
            {"row": {"answer": "synthetic:" + q["id"]}, "provenance": {"path": "synthetic"}},
        )
        fresh.append(q["id"])
        context.progress("synthetic-row", index + 1, len(snapshot["questions"]))
        if snapshot.get("fail_after_two") and not snapshot.get("retry_of") and index == 1:
            raise RuntimeError("Synthetic provider429/failure after accepted rows")
        if snapshot.get("slow"):
            time.sleep(0.6)
    return {
        "rows": [{"id": q["id"], "answer": "synthetic:" + q["id"]} for q in snapshot["questions"]],
        "fresh_ids": fresh,
        "resumed_ids": list(accepted),
    }


synthetic_checkpoint_worker.requires_complete_checkpoints = True


def synthetic_incumbent_worker(snapshot, context):
    value = {
        "valid": True,
        "metrics": {"coverage": 0.5, "covered_area_mm2": 25},
        "placements": [{"id": "fixture"}],
    }
    context.incumbent(value)
    context.incumbent(value)
    return value


def synthetic_incumbent_validator(snapshot, value):
    return value.get("valid") is True


def wait(client, job_id, states, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = client.get("/api/v1/jobs/" + job_id).json()
        if value["state"] in states:
            return value
        time.sleep(0.05)
    raise AssertionError(value)


def pinned_snapshot(dataset_id):
    pack = ROOT / "inputs/PACK_for_teams"

    def csv_rows(name):
        return list(csv.DictReader(io.StringIO((pack / name).read_text(encoding="utf-8-sig"))))

    return {
        "dataset_id": dataset_id,
        "questions": [{"id": f"OTHER-{n}", "question": "Synthetic protocol question"} for n in range(3)],
        "kb_bytes_b64": base64.b64encode(
            (pack / "2_assistant_crm/ksm_knowledge_base.json").read_bytes()
        ).decode(),
        "materials_bytes_b64": base64.b64encode((pack / "1_ostatki/materials.csv").read_bytes()).decode(),
        "materials": csv_rows("1_ostatki/materials.csv"),
        "ai_profile": "local_limited",
        "ai_settings": {},
    }


def test_accepted_rows_survive_failure_restart_and_retry_without_repeating_them(client, imported):
    co = client.app.state.coordinator
    co.handlers["synthetic-checkpoints"] = Handler(
        synthetic_checkpoint_worker, lane="network", checkpoint_validate=synthetic_row_validator
    )
    factory = client.app.state.session_factory
    snapshot = pinned_snapshot(imported["dataset_id"]) | {"fail_after_two": True}
    with write_transaction(factory) as s:
        job = enqueue(s, imported["dataset_id"], "synthetic-checkpoints", snapshot)
        jid = job.id
    result = wait(client, jid, {"failed"})
    assert result["accepted_row_count"] == 2 and result["result"] is None
    # Simulated process coordinator replacement uses persisted records, not its former memory.
    co.stop()
    replacement = Coordinator(factory, co.handlers)
    replacement.start()
    client.app.state.coordinator = replacement
    try:
        response = client.post(
            f"/api/v1/jobs/{jid}/retry",
            params={"dataset_id": imported["dataset_id"]},
            headers={"Idempotency-Key": "actual-retry-protocol"},
        )
        assert response.status_code == 202, response.text
        result = wait(client, response.json()["job_id"], {"completed", "failed"})
        assert result["state"] == "completed", result
        assert result["result"]["resumed_ids"] == ["OTHER-0", "OTHER-1"]
        assert result["result"]["fresh_ids"] == ["OTHER-2"] and result["accepted_row_count"] == 3
        assert len(result["result"]["rows"]) == 3
    finally:
        replacement.stop()


def test_cancel_preserves_only_received_rows_and_late_attempt_is_ignored(client, imported):
    co = client.app.state.coordinator
    co.handlers["synthetic-checkpoints"] = Handler(
        synthetic_checkpoint_worker, lane="network", checkpoint_validate=synthetic_row_validator
    )
    factory = client.app.state.session_factory
    snapshot = pinned_snapshot(imported["dataset_id"]) | {"slow": True}
    with write_transaction(factory) as s:
        job = enqueue(s, imported["dataset_id"], "synthetic-checkpoints", snapshot)
        jid = job.id
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        value = client.get("/api/v1/jobs/" + jid).json()
        if value["accepted_row_count"] >= 1:
            break
        time.sleep(0.03)
    active = co.active[jid]
    co.accept_checkpoint(jid, active, {"attempt_id": "previous-worker-attempt"})
    assert client.get("/api/v1/jobs/" + jid).json()["state"] == "running"
    r = client.post("/api/v1/jobs/" + jid + "/cancel", params={"dataset_id": imported["dataset_id"]})
    assert r.status_code == 200
    value = wait(client, jid, {"cancelled"})
    assert value["accepted_row_count"] >= 1 and value["accepted_row_count"] < 3


def test_parent_replays_trusted_pricing_and_identity_invalidates_context(client, imported):
    from glassflow.core.domain_jobs import engine_for
    from glassflow.modules.intelligence.assistant.tools import ToolContext, execute_tool

    snapshot = pinned_snapshot(imported["dataset_id"])
    snapshot["questions"] = [
        {"id": "Changed-ID", "question": "Стекло 6 мм прозрачное 450×370 мм с кромкой по периметру"}
    ]
    fp = row_fingerprint(snapshot, "Changed-ID")
    engine = engine_for(snapshot, type("Ctx", (), {"private_config": {}})())
    ctx = ToolContext(
        engine.kb, engine.mappings, snapshot["dataset_id"], user_text=snapshot["questions"][0]["question"]
    )
    arguments = {
        "catalog_product_id": "steklo-6-prozrachnoe",
        "length_mm": 450,
        "width_mm": 370,
        "quantity": 1,
        "processing": "euro_edge",
        "edge_sides": "all",
    }
    execute_tool(ctx, "calculate_quote", arguments)
    payload = {
        "row": {"answer": ctx.facts.render("[[quote]]")},
        "inventory_used": False,
        "provenance": {"path": "llm_tools", "verifier_status": "supported"},
        "tool_calls": [{"name": "calculate_quote", "arguments": arguments}],
    }
    assert validate_assistant_checkpoint(snapshot, "Changed-ID", fp, payload)
    bad = deepcopy(payload)
    bad["row"]["answer"] = "Серое 8 мм стоит 8000 ₸ за м²."
    assert not validate_assistant_checkpoint(snapshot, "Changed-ID", fp, bad)
    for changed in [
        dict(ai_settings={"model_id": "different"}),
        dict(ai_profile="direct"),
        dict(kb_bytes_b64="changed-KB"),
        dict(materials_bytes_b64="changed-materials"),
        dict(input_source_hashes={"questions": "different-original-byte-hash"}),
        dict(questions=[{"id": "Changed-ID", "question": "different quantity 2"}]),
    ]:
        assert row_fingerprint(snapshot | changed, "Changed-ID") != fp
    bad = deepcopy(payload)
    bad["inventory_used"] = True
    assert not validate_assistant_checkpoint(snapshot, "Changed-ID", fp, bad)
    bad = deepcopy(payload)
    bad["tool_calls"].append({"name": "find_remnants", "arguments": {}})
    assert not validate_assistant_checkpoint(snapshot, "Changed-ID", fp, bad)


def test_failed_restore_replacement_preserves_automatic_export_configuration(client):
    coordinator = client.app.state.coordinator
    expected = {"data_dir": client.app.state.data_dir, "services": client.app.state.services}
    coordinator.configure_export_context(**expected)
    token = client.get("/api/v1/session").json()["session_token"]
    response = client.post(
        "/api/v1/system/restore",
        json={"backup_id": "missing-backup", "confirm_replace": True},
        headers={"X-GlassFlow-Session": token},
    )
    assert response.status_code == 404
    replacement = client.app.state.coordinator
    assert replacement is not coordinator and replacement.export_context == expected
    assert replacement.healthy


def test_parent_records_actual_incumbent_and_stop_timeline_without_placements(client, imported):
    co = client.app.state.coordinator
    factory = client.app.state.session_factory
    co.handlers["synthetic-incumbent"] = Handler(
        synthetic_incumbent_worker, validate=synthetic_incumbent_validator
    )
    with write_transaction(factory) as s:
        job = enqueue(s, imported["dataset_id"], "synthetic-incumbent", {})
        jid = job.id
    assert wait(client, jid, {"completed"})["state"] == "completed"
    with factory() as s:
        events = s.scalars(select(AuditRow).where(AuditRow.object_id == jid).order_by(AuditRow.id)).all()
        values = [e.versions for e in events if e.action == "job.valid_incumbent"]
        assert len(values) == 1 and values[0]["metrics"]["covered_area_mm2"] == 25
        assert values[0]["elapsed_seconds"] >= 0 and "placements" not in values[0]
        assert events[-1].action == "job.stopped" and events[-1].versions["state"] == "completed"


def test_expired_utc_budget_after_restart_does_not_receive_a_fresh_duration(client, imported):
    co = client.app.state.coordinator
    co.stop()
    factory = client.app.state.session_factory
    budget = create_budget(60, 10, {})
    budget["work_deadline_utc"] = (utc_now() - timedelta(seconds=1)).isoformat()
    with write_transaction(factory) as s:
        job = enqueue(s, imported["dataset_id"], "synthetic-incumbent", {"run_budget": budget})
        jid = job.id
    replacement = Coordinator(
        factory,
        {"synthetic-incumbent": Handler(synthetic_incumbent_worker, validate=synthetic_incumbent_validator)},
    )
    # Startup must mark persisted queued/running work interrupted; retry carries the old UTC expiry.
    replacement.start()
    replacement.stop()
    with factory() as s:
        assert s.get(JobRow, jid).state == "interrupted"
    with write_transaction(factory) as s:
        retry = enqueue(
            s, imported["dataset_id"], "synthetic-incumbent", {"run_budget": budget, "retry_of": jid}
        )
        rid = retry.id
    second = Coordinator(
        factory,
        {"synthetic-incumbent": Handler(synthetic_incumbent_worker, validate=synthetic_incumbent_validator)},
    )
    # Dispatch directly rather than start recovery, which intentionally marks prior queued work interrupted.
    second.dispatch()
    with factory() as s:
        row = s.get(JobRow, rid)
        assert row.state == "failed" and row.error_code == "RUN_WORK_BUDGET_EXCEEDED"


def test_opt_in_auto_exports_real_full_baseline_before_improvement(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from glassflow.main import create_app

    with TestClient(create_app(tmp_path, testing=True)) as c:
        c.get("/api/v1/session")
        source = c.post("/api/v1/datasets/demo", headers={"Idempotency-Key": "budget-source"}).json()
        buyers = c.post(
            "/api/v1/buyers/import",
            params={"dataset_id": source["dataset_id"]},
            files={
                "file": ("buyers.csv", (ROOT / "data/buyers/buyers.platform.csv").read_bytes()),
                "evidence": ("evidence.json", (ROOT / "data/buyers/evidence.platform.json").read_bytes()),
            },
            headers={"Idempotency-Key": "budget-buyers"},
        ).json()
        response = c.post(
            "/api/v1/runs",
            json={
                "dataset_id": source["dataset_id"],
                "config_version": "budget-regression",
                "buyer_registry_version": buyers["version"],
                "total_budget_seconds": 75,
                "export_reserve_seconds": 15,
                "solver_config": {
                    "profile": "extended",
                    "time_limit_seconds": 45,
                    "workers": 1,
                    "minimum_free_remnants": 5,
                },
            },
            headers={"Idempotency-Key": "opt-in"},
        )
        assert response.status_code == 202, response.text
        run_id = response.json()["run_id"]
        deadline = time.monotonic() + 55
        while time.monotonic() < deadline:
            run = c.get("/api/v1/runs/" + run_id).json()
            if run["manifest"].get("accepted_export_id") and run["budget"].get("improvement_job_id"):
                break
            time.sleep(0.2)
        assert run["manifest"].get("accepted_export_id"), run
        assert run["budget"]["baseline_accepted_at"]
        improved = run["budget"]["improvement_job_id"]
        accepted = run["manifest"]["accepted_export_id"]
        dataset_id = run["manifest"]["dataset_id"]
        assert c.get(f"/api/v1/runs/{run_id}/files/{accepted}/answers.csv").status_code == 200
        c.post("/api/v1/jobs/" + improved + "/cancel", params={"dataset_id": dataset_id})
        wait(c, improved, {"cancelled", "completed"}, timeout=20)
        current = c.get("/api/v1/runs/" + run_id).json()
        assert current["manifest"]["accepted_export_id"] == accepted
        assert len(current["manifest"]["accepted_files"]) == 6
        with c.app.state.session_factory() as s:
            row = s.get(JobRow, improved)
            assert row.input["phase"] == "improvement"
            if row.started_at:
                assert row.started_at >= run["budget"]["baseline_accepted_at"]
        # A validator completing under a replaced explicit budget cannot replace the accepted package.
        from glassflow.contracts.platform import RunBudgetRenew
        from glassflow.modules.platform import exports, runs

        original_validator = exports.official_cutting
        old_budget_version = current["budget"]["version"]

        def renew_while_validating(*args, **kwargs):
            result = original_validator(*args, **kwargs)
            with write_transaction(c.app.state.session_factory) as session:
                current_run = runs.find_run(session, run_id)
                runs.renew_budget(
                    session,
                    run_id,
                    RunBudgetRenew(
                        dataset_id=dataset_id,
                        expected_version=current_run.version,
                        total_budget_seconds=75,
                        export_reserve_seconds=15,
                    ),
                    "concurrent-renewal-test",
                )
            return result

        monkeypatch.setattr(exports, "official_cutting", renew_while_validating)
        attempt = exports.export_run(
            c.app.state.session_factory,
            run_id,
            c.app.state.data_dir,
            c.app.state.services,
            "late-budget-test",
            expected_budget_version=old_budget_version,
        )
        assert attempt["status"] == "partial" and any("RUN_BUDGET_CHANGED" in e for e in attempt["errors"])
        assert c.get("/api/v1/runs/" + run_id).json()["manifest"]["accepted_export_id"] == accepted


def test_expired_run_retry_requires_explicit_new_budget_and_renewal_is_idempotent(client, imported):
    response = client.post(
        "/api/v1/runs",
        json={
            "dataset_id": imported["dataset_id"],
            "config_version": "renewal-test",
            "modules": ["crm"],
            "total_budget_seconds": 60,
            "export_reserve_seconds": 10,
        },
        headers={"Idempotency-Key": "renewal-run"},
    )
    assert response.status_code == 202, response.text
    job = wait(client, response.json()["job_id"], {"completed"})
    run_id = job["run_id"]
    factory = client.app.state.session_factory
    with write_transaction(factory) as session:
        row = session.query(ObjectRow).filter_by(kind="run", id=run_id).one()
        old = {**row.data["budget"], "work_deadline_utc": (utc_now() - timedelta(seconds=1)).isoformat()}
        row.data = {**row.data, "budget": old}
        original = session.get(JobRow, job["job_id"])
        interrupted = enqueue(session, row.dataset_id, "crm", deepcopy(original.input), run_id)
        interrupted.state, interrupted.stopped = "interrupted", True
        retry_id = interrupted.id
    url = f"/api/v1/jobs/{retry_id}/retry"
    rejected = client.post(
        url, params={"dataset_id": job["dataset_id"]}, headers={"Idempotency-Key": "expired"}
    )
    assert rejected.status_code == 409 and rejected.json()["code"] == "RUN_BUDGET_EXPIRED"
    body = {
        "dataset_id": job["dataset_id"],
        "expected_version": 0,
        "total_budget_seconds": 60,
        "export_reserve_seconds": 10,
    }
    renew = client.post(
        f"/api/v1/runs/{run_id}/budget", json=body, headers={"Idempotency-Key": "new-explicit-budget"}
    )
    assert renew.status_code == 200, renew.text
    replay = client.post(
        f"/api/v1/runs/{run_id}/budget", json=body, headers={"Idempotency-Key": "new-explicit-budget"}
    )
    assert replay.json() == renew.json() and renew.json()["budget"]["version"] == 1
    retry = client.post(
        url, params={"dataset_id": job["dataset_id"]}, headers={"Idempotency-Key": "after-renew"}
    )
    assert retry.status_code == 202, retry.text
    assert wait(client, retry.json()["job_id"], {"completed", "failed"})["state"] == "completed"


def test_real_assistant_engine_429_keeps_verified_local_rows_and_fallback_origin(imported, monkeypatch):
    import asyncio

    from glassflow.core import domain_jobs
    from glassflow.modules.intelligence.assistant.engine import AssistantEngine
    from glassflow.modules.intelligence.providers.base import ProviderError
    from glassflow.modules.intelligence.providers.policy import (
        AIProfile,
        MemoryLedger,
        ModelRef,
        ResilientClient,
    )
    from glassflow.modules.intelligence.providers.settings import AIRuntime

    class RateLimitedProvider:
        calls = 0

        async def generate(self, request):
            self.calls += 1
            raise ProviderError("rate_limit", "Synthetic429", status=429, retry_after_s=600)

    snapshot = pinned_snapshot(imported["dataset_id"])
    snapshot["questions"] = [
        {"id": "A", "question": "Стекло 6 мм прозрачное 450×370 мм с кромкой по периметру"},
        {"id": "B", "question": "Выполняете ли монтаж?"},
        {"id": "C", "question": "Хочу что-нибудь красивое на кухню, посоветуйте"},
    ]
    snapshot["ai_profile"] = "direct"
    local = domain_jobs.engine_for(snapshot, type("C", (), {"private_config": {}})())
    provider = RateLimitedProvider()
    profile = AIProfile(
        primary=ModelRef(provider="gemini", model_id="gemini-3.5-flash-lite"),
        max_retries=0,
        rpm=None,
        tpm=None,
        rpd=None,
    )
    client = ResilientClient(
        profile=profile,
        providers={profile.primary.label: provider},
        ledger=MemoryLedger(),
        prompt_version="test",
        sleep=lambda _: asyncio.sleep(0),
    )
    runtime = AIRuntime(profile, client, "available", None, {"gemini": True})
    engine = AssistantEngine(local.kb, local.mappings, dataset_id=snapshot["dataset_id"], runtime=runtime)
    monkeypatch.setattr(domain_jobs, "engine_for", lambda *_: engine)

    class RecordingContext:
        private_config = {}
        accepted = []

        def progress(self, *_):
            pass

        def remaining_seconds(self):
            return 20

        def checkpoint(self, row_id, fingerprint, payload):
            assert validate_assistant_checkpoint(snapshot, row_id, fingerprint, payload)
            self.accepted.append(payload)

    context = RecordingContext()
    result = domain_jobs.assistant_job(snapshot, context)
    paths = result["provenance"]["answer_paths"]
    assert len(result["rows"]) == 3 and len(context.accepted) == 3
    assert provider.calls == 1
    assert [p["path"] for p in paths] == ["deterministic", "deterministic", "fallback"]
    assert paths[-1]["provider_error_kind"] == "rate_limit" and paths[-1]["provider_error_status"] == 429
