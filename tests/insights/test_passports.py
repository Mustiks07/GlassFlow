import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from glassflow.core.models import AuditRow, JobRow, ObjectRow
from glassflow.main import create_app


@pytest.fixture()
def runtime(tmp_path):
    with TestClient(create_app(tmp_path, testing=True)) as client:
        client.get("/api/v1/session")
        source = client.post("/api/v1/datasets/demo", headers={"Idempotency-Key": "passport-source"}).json()
        yield client, source["dataset_id"], None


def test_accepted_passport_pins_old_jobs_and_checks_bytes(runtime, tmp_path):
    client, source, _ = runtime
    content = b"verified exact bytes"
    digest = hashlib.sha256(content).hexdigest()
    run_id, export_id = "passport-run", "accepted-one"
    manifest = {
        "run_id": run_id,
        "dataset_id": source,
        "source_dataset_id": source,
        "modules": ["cutting"],
        "accepted_export_id": export_id,
        "accepted_files": {"solution.csv": digest},
    }
    with client.app.state.session_factory.begin() as session:
        session.add(ObjectRow(dataset_id=source, kind="run", id=run_id, version=0, data=manifest))
        for jid, area in [("old-job", 10), ("later-job", 20)]:
            session.add(
                JobRow(
                    dataset_id=source,
                    id=jid,
                    run_id=run_id,
                    kind="cutting",
                    state="completed",
                    stage="completed",
                    input={},
                    result={"metrics": {"covered_area_mm2": area}, "stop_reason": "deadline"},
                    error_code=None,
                    total=1,
                    started_at=None,
                    finished_at=None,
                )
            )
        session.add(
            AuditRow(
                dataset_id=source,
                action="job.valid_incumbent",
                object_id="old-job",
                correlation_id="test",
                versions={"elapsed_seconds": 0.25, "metrics": {"covered_area_mm2": 10}},
            )
        )
    directory = tmp_path / "exports" / run_id / export_id
    directory.mkdir(parents=True)
    (directory / "solution.csv").write_bytes(content)
    accepted = {
        **manifest,
        "export_id": export_id,
        "status": "ready",
        "files": {"solution.csv": digest},
        "result_refs": {"cutting": {"job_id": "old-job", "state": "completed"}},
    }
    (directory / "manifest.json").write_text(json.dumps(accepted), encoding="utf-8")
    url = f"/api/v1/runs/{run_id}/passport"
    value = client.get(url, params={"dataset_id": source, "view": "accepted"})
    assert value.status_code == 200, value.text
    value = value.json()
    assert value["modules"][0]["job_id"] == "old-job"
    assert value["modules"][0]["metrics"]["covered_area_mm2"] == 10
    assert value["history_available"]
    assert value["modules"][0]["history"][0]["elapsed_seconds"] == 0.25
    assert client.get(url, params={"dataset_id": "other"}).status_code == 404
    (directory / "solution.csv").write_bytes(b"modified")
    assert client.get(url, params={"dataset_id": source, "view": "accepted"}).status_code == 409


def test_no_accepted_bundle_is_not_claimed_ready(runtime):
    client, source, _ = runtime
    with client.app.state.session_factory.begin() as session:
        session.add(
            ObjectRow(
                dataset_id=source,
                kind="run",
                id="partial-run",
                version=0,
                data={"run_id": "partial-run", "dataset_id": source, "modules": ["cutting"]},
            )
        )
    response = client.get(
        "/api/v1/runs/partial-run/passport", params={"dataset_id": source, "view": "accepted"}
    )
    assert response.status_code == 409
    current = client.get("/api/v1/runs/partial-run/passport", params={"dataset_id": source}).json()
    assert current["status"] == "blocked" and not current["history_available"]


def test_actual_full_export_passport_remains_pinned_after_another_real_cutting_job(runtime):
    import time
    from copy import deepcopy
    from pathlib import Path

    from glassflow.core.jobs import enqueue
    from glassflow.core.uow import write_transaction
    client, source, _ = runtime
    root = Path(__file__).resolve().parents[2]
    imported = client.post("/api/v1/buyers/import", params={"dataset_id": source},
        files={"file": ("buyers.csv", (root / "data/buyers/buyers.platform.csv").read_bytes()),
               "evidence": ("evidence.json", (root / "data/buyers/evidence.platform.json").read_bytes())},
        headers={"Idempotency-Key": "actual-passport-buyers"})
    assert imported.status_code == 200, imported.text
    started = client.post("/api/v1/runs", json={"dataset_id": source, "config_version": "actual-passport-check",
        "buyer_registry_version": imported.json()["version"], "solver_config": {"profile": "quick", "time_limit_seconds": 2}},
        headers={"Idempotency-Key": "actual-passport-run"})
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        view = client.get(f"/api/v1/runs/{run_id}").json()
        if view["status"] != "running":
            break
        time.sleep(.1)
    assert view["status"] == "completed", view
    exported = client.post(f"/api/v1/runs/{run_id}/export", headers={"Idempotency-Key": "actual-passport-export"})
    assert exported.status_code == 200 and exported.json()["status"] == "ready", exported.text
    url = f"/api/v1/runs/{run_id}/passport"
    before = client.get(url, params={"dataset_id": source, "view": "accepted"}).json()
    assert set(before["files"]) == {"solution.csv", "answers.csv", "picks.csv", "verdicts.csv",
                                    "sale_cards.csv", "buyers_top50.csv"}
    old_cut = next(m for m in before["modules"] if m["module"] == "cutting")
    factory = client.app.state.session_factory
    with write_transaction(factory) as session:
        job = session.get(JobRow, old_cut["job_id"])
        copied = deepcopy(job.input)
        copied.pop("attempt_id", None)
        new = enqueue(session, job.dataset_id, "cutting", copied, run_id)
        new_id = new.id
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        value = client.get(f"/api/v1/jobs/{new_id}").json()
        if value["state"] not in {"running", "queued"}:
            break
        time.sleep(.1)
    assert value["state"] == "completed", value
    current = client.get(url, params={"dataset_id": source, "view": "current"}).json()
    after = client.get(url, params={"dataset_id": source, "view": "accepted"}).json()
    assert next(m for m in current["modules"] if m["module"] == "cutting")["job_id"] == new_id
    assert after == before  # Includes pinned metrics, histories, refs, hashes and provenance.
    for name, uri in exported.json()["files"].items():
        if name == "manifest.json":
            continue
        response = client.get(uri)
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == after["files"][name]
