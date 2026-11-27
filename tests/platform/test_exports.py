import csv
import io
import time

import pytest

from glassflow.core.models import JobRow
from glassflow.core.uow import write_transaction
from glassflow.modules.platform.exports import validate_rows
from glassflow.modules.platform.imports import records


def test_partial_download_exact_utf8_and_replay(client, imported):
    job = client.post("/api/v1/runs", json={"dataset_id": imported["dataset_id"], "modules": ["crm"],
                     "config_version": "synthetic-v1"}, headers={"Idempotency-Key": "run"}).json()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        progress = client.get(f"/api/v1/jobs/{job['job_id']}").json()
        if progress["state"] == "completed":
            break
        time.sleep(0.05)
    url = f"/api/v1/runs/{job['run_id']}/export"
    response = client.post(url, headers={"Idempotency-Key": "export"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "partial"
    assert set(result["files"]) == {"picks.csv", "manifest.json"}
    content = client.get(result["files"]["picks.csv"]).content
    assert not content.startswith(b"\xef\xbb\xbf")
    reader = csv.DictReader(io.StringIO(content.decode("utf8"), newline=""))
    assert reader.fieldnames == ["app_id"] and len(list(reader)) == 25
    assert client.post(url, headers={"Idempotency-Key": "export"}).json() == result
    manifest = client.get(result["files"]["manifest.json"]).json()
    assert manifest["official_accuracy"] == dict(assistant=None, crm=None, quality=None)
    assert len(manifest["files"]["picks.csv"]) == 64


def test_organizer_validator_and_strict_additional_checks(client, imported):
    # Explicit synthetic solver result: all parts NEW. This checks format/official invocation only.
    from glassflow.contracts.platform import RunRequest
    from glassflow.core.jobs import enqueue
    from glassflow.modules.platform.exports import export_run
    from glassflow.modules.platform.runs import create_run
    factory = client.app.state.session_factory
    with write_transaction(factory) as session:
        run_job = create_run(session, RunRequest(dataset_id=imported["dataset_id"], modules=["cutting"],
            config_version="synthetic-v1"), client.app.state.services, "synthetic")
        job = session.get(JobRow, run_job["job_id"])
        rows = [{"part_id": r.public_id, "remnant_id": "NEW", "x_mm": "", "y_mm": "", "rot": ""}
                for r in records(session, job.dataset_id, "orders")]
        job.state, job.result = "completed", {"rows": rows, "validated": True, "plan_id": "synthetic", "plan_revision": 0}
        # NEEDS_REVIEW must not become a false OK export.
        quality = enqueue(session, job.dataset_id, "quality", {}, job.run_id)
        quality.state, quality.result = "completed", {"rows": [{"id": "D01", "verdict": "NEEDS_REVIEW", "correct": ""}]}
        with pytest.raises(Exception):
            validate_rows(session, job.dataset_id, "solution.csv", rows[:-1])
        with pytest.raises(Exception):
            validate_rows(session, job.dataset_id, "solution.csv", rows + [rows[0]])
        with pytest.raises(Exception):
            validate_rows(session, job.dataset_id, "solution.csv", [dict(rows[0], x_mm="0")] + rows[1:])
    result = export_run(factory, run_job["run_id"], client.app.state.data_dir, client.app.state.services, "synthetic")
    assert "solution.csv" in result["files"] and "verdicts.csv" not in result["files"]
    manifest = client.get(result["files"]["manifest.json"]).json()
    official = manifest["validators"]["cutting_official"]
    assert official["passed"] and official["exit_code"] == 0 and "invalid=0" in official["stdout"]
