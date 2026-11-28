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
