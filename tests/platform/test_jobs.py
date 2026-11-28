import time

from sqlalchemy import select

from glassflow.core.jobs import Coordinator, Handler, enqueue
from glassflow.core.models import JobRow
from glassflow.core.uow import write_transaction


def synthetic_worker(snapshot, context):
    context.progress("synthetic", 1, 2)
    context.incumbent({"valid": True, "value": snapshot["value"]})
    for _ in range(100):
        if context.cancelled():
            return {"valid": True, "cancel_seen": True}
        time.sleep(0.03)
    return {"valid": True, "value": snapshot["value"]}


def synthetic_validator(snapshot, result):
    return result.get("valid") is True


def synthetic_private_worker(snapshot, context):
    return {
        "key_present": context.private_config.get("api_key") == "synthetic-session-key",
        "retried": bool(snapshot.get("retry_of")),
    }


def wait_job(client, job_id, state, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = client.get(f"/api/v1/jobs/{job_id}").json()
        if row["state"] in state:
            return row
        time.sleep(0.05)
    raise AssertionError(row)


def test_independent_run_crm_and_missing_dependencies(client, imported):
    response = client.post(
        "/api/v1/runs",
        json={"dataset_id": imported["dataset_id"], "config_version": "test-v1"},
        headers={"Idempotency-Key": "run"},
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = client.get(f"/api/v1/runs/{run_id}").json()
        if result["status"] == "partial":
            break
        time.sleep(0.05)
    assert result["status"] == "partial", result
    crm = next(j for j in result["jobs"] if j["stage"] == "completed")
    assert len(crm["result"]["rows"]) == 25
    assert crm["dataset_id"] != imported["dataset_id"]
    assert result["manifest"]["official_accuracy"] == dict(assistant=None, crm=None, quality=None)
    assert set(result["missing_modules"]) == {"cutting", "assistant", "quality", "cards"}


def test_cancel_keeps_valid_incumbent_and_restart_interrupted(client, imported):
    coordinator = client.app.state.coordinator
    coordinator.handlers["synthetic"] = Handler(synthetic_worker, validate=synthetic_validator)
    factory = client.app.state.session_factory
    with write_transaction(factory) as session:
        job = enqueue(session, imported["dataset_id"], "synthetic", {"value": 12})
        job_id = job.id
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        current = client.get(f"/api/v1/jobs/{job_id}").json()
        if current["last_valid_result"]:
            break
        time.sleep(0.05)
    assert current["last_valid_result"]["value"] == 12
    cancel = client.post(
        f"/api/v1/jobs/{job_id}/cancel", params={"dataset_id": imported["dataset_id"]}
    ).json()
    assert cancel["cancel_requested"] is True
    cancelled = wait_job(client, job_id, {"cancelled"})
    assert cancelled["stopped"] is True and cancelled["last_valid_result"]["value"] == 12
    coordinator.stop()
    with write_transaction(factory) as session:
        orphan = enqueue(session, imported["dataset_id"], "synthetic", {})
        orphan.state = "running"
        orphan.last_valid_result = {"valid": True}
        orphan_id = orphan.id
    replacement = Coordinator(factory, {})
    replacement.start()
    replacement.stop()
    with factory() as session:
        row = session.scalar(select(JobRow).where(JobRow.id == orphan_id))
        assert row.state == "interrupted" and row.last_valid_result == {"valid": True}


def test_network_secret_only_memory_and_retry_idempotent(client, imported):
    owner = {"X-GlassFlow-Session": client.get("/api/v1/session").json()["session_token"]}
    response = client.patch(
        "/api/v1/settings",
        json={"profile": "direct", "model_id": "synthetic-free-model", "api_key": "synthetic-session-key"},
        headers=owner,
    )
    assert response.status_code == 200
    client.app.state.coordinator.handlers["assistant"] = Handler(synthetic_private_worker, lane="network")
    started = client.post(
        "/api/v1/runs",
        json={
            "dataset_id": imported["dataset_id"],
            "modules": ["assistant"],
            "ai_profile": "direct",
            "config_version": "synthetic-private-test",
        },
        headers={"Idempotency-Key": "private-run"},
    ).json()
    result = wait_job(client, started["job_id"], {"completed", "failed"})
    assert result["state"] == "completed" and result["result"]["key_present"] is True
    factory = client.app.state.session_factory
    with write_transaction(factory) as session:
        previous = enqueue(session, imported["dataset_id"], "assistant", {"ai_profile": "local_limited"})
        previous.state = "interrupted"
        previous_id = previous.id
    url = f"/api/v1/jobs/{previous_id}/retry"
    response = client.post(
        url, params={"dataset_id": imported["dataset_id"]}, headers={"Idempotency-Key": "retry"}
    )
    assert response.status_code == 202, response.text
    again = client.post(
        url, params={"dataset_id": imported["dataset_id"]}, headers={"Idempotency-Key": "retry"}
    )
    assert again.json() == response.json()
    retried = wait_job(client, response.json()["job_id"], {"completed"})
    assert retried["retry_of"] == previous_id and retried["result"]["retried"] is True
    # Windows may deny ordinary reads of SQLite's live memory-mapped SHM index.
    # Drain the real coordinator and close its DB handles before scanning every
    # remaining database/sidecar byte; do not skip unreadable files or this check.
    client.app.state.coordinator.stop()
    client.app.state.engine.dispose()
    database_files = list(client.app.state.data_dir.glob("*.db*"))
    assert any(p.name == "glassflow.db" and p.stat().st_size for p in database_files)
    assert not any(b"synthetic-session-key" in p.read_bytes() for p in database_files)
