import csv
import io
import time

import pytest

from glassflow.core.models import JobRow
from glassflow.core.uow import write_transaction
from glassflow.modules.platform.exports import validate_rows
from glassflow.modules.platform.imports import records


def test_partial_download_exact_utf8_and_replay(client, imported):
    job = client.post(
        "/api/v1/runs",
        json={"dataset_id": imported["dataset_id"], "modules": ["crm"], "config_version": "synthetic-v1"},
        headers={"Idempotency-Key": "run"},
    ).json()
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
        run_job = create_run(
            session,
            RunRequest(dataset_id=imported["dataset_id"], modules=["cutting"], config_version="synthetic-v1"),
            client.app.state.services,
            "synthetic",
        )
        job = session.get(JobRow, run_job["job_id"])
        rows = [
            {"part_id": r.public_id, "remnant_id": "NEW", "x_mm": "", "y_mm": "", "rot": ""}
            for r in records(session, job.dataset_id, "orders")
        ]
        job.state, job.result = (
            "completed",
            {"rows": rows, "validated": True, "plan_id": "synthetic", "plan_revision": 0},
        )
        # NEEDS_REVIEW must not become a false OK export.
        quality = enqueue(session, job.dataset_id, "quality", {}, job.run_id)
        quality.state, quality.result = (
            "completed",
            {"rows": [{"id": "D01", "verdict": "NEEDS_REVIEW", "correct": ""}]},
        )
        with pytest.raises(Exception):
            validate_rows(session, job.dataset_id, "solution.csv", rows[:-1])
        with pytest.raises(Exception):
            validate_rows(session, job.dataset_id, "solution.csv", rows + [rows[0]])
        with pytest.raises(Exception):
            validate_rows(session, job.dataset_id, "solution.csv", [dict(rows[0], x_mm="0")] + rows[1:])
    result = export_run(
        factory, run_job["run_id"], client.app.state.data_dir, client.app.state.services, "synthetic"
    )
    assert "solution.csv" in result["files"] and "verdicts.csv" not in result["files"]
    manifest = client.get(result["files"]["manifest.json"]).json()
    official = manifest["validators"]["cutting_official"]
    assert official["passed"] and official["exit_code"] == 0 and "invalid=0" in official["stdout"]


def test_all_five_exact_downloads_on_new_ids_with_explicit_domain_fixtures(client, uploads, services):
    """Format/integration seam check only; synthetic C2/C3/buyer fixtures are not domain acceptance."""
    from conftest import import_dataset
    from sales.test_sales import SyntheticSource, import_synthetic_buyers
    from sqlalchemy import select

    from glassflow.core.jobs import enqueue

    transformed = []
    keys = {
        "stock": ["remnant_id"],
        "orders": ["order_id", "part_id"],
        "applications": ["app_id", "client_id"],
        "questions": ["id"],
        "dialogs": ["id"],
    }
    for name, content in uploads:
        kind = next((k for k in keys if name.startswith(k)), None)
        if kind:
            reader = csv.DictReader(io.StringIO(content.decode("utf8"), newline=""))
            fields, rows = reader.fieldnames, list(reader)
            for row in rows:
                for field in keys[kind]:
                    row[field] = "SYNTHETIC-" + row[field]
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            content = buffer.getvalue().encode("utf8")
        transformed.append((name, content))
    imported = import_dataset(client, transformed)
    version = import_synthetic_buyers(client, imported["dataset_id"])
    services.sales_source = SyntheticSource()
    started = client.post(
        "/api/v1/runs",
        json={
            "dataset_id": imported["dataset_id"],
            "config_version": "synthetic-seams",
            "buyer_registry_version": version,
        },
        headers={"Idempotency-Key": "full-format-run"},
    ).json()
    factory = client.app.state.session_factory
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        view = client.get(f"/api/v1/runs/{started['run_id']}").json()
        if not any(j["state"] in {"queued", "running"} for j in view["jobs"]):
            break
        time.sleep(0.05)
    d = view["manifest"]["dataset_id"]
    cards = client.post(
        "/api/v1/sale-cards",
        json={
            "dataset_id": d,
            "plan_id": "synthetic-plan",
            "plan_revision": 1,
            "buyer_registry_version": version,
        },
        headers={"Idempotency-Key": "full-cards"},
    ).json()
    assert isinstance(cards, list) and len(cards) == 5, cards
    with write_transaction(factory) as session:
        jobs = {j.kind: j for j in session.scalars(select(JobRow).where(JobRow.run_id == started["run_id"]))}
        outputs = {
            "cutting": {
                "rows": [
                    {"part_id": r.public_id, "remnant_id": "NEW", "x_mm": "", "y_mm": "", "rot": ""}
                    for r in records(session, d, "orders")
                ],
                "plan_id": "synthetic-plan",
                "plan_revision": 1,
                "validated": True,
            },
            "assistant": {
                "rows": [
                    {"id": r.public_id, "answer": "Явный синтетический ответ теста формата, не C3 runtime."}
                    for r in records(session, d, "questions")
                ]
            },
            "quality": {
                "rows": [
                    {"id": r.public_id, "verdict": "OK", "correct": ""}
                    for r in records(session, d, "dialogs")
                ]
            },
            "cards": {
                "card_ids": [c["card_id"] for c in cards],
                "plan_id": "synthetic-plan",
                "plan_revision": 1,
            },
        }
        for kind, result in outputs.items():
            job = jobs.get(kind) or enqueue(session, d, kind, {}, started["run_id"])
            job.state, job.stage, job.result = (
                "completed",
                "completed",
                {**result, "provenance": {"synthetic": True}},
            )
    result = client.post(
        f"/api/v1/runs/{started['run_id']}/export", headers={"Idempotency-Key": "full-export"}
    ).json()
    assert result["status"] == "ready", result
    from glassflow.modules.platform.exports import SCHEMAS

    for name, fields in SCHEMAS.items():
        content = client.get(result["files"][name]).content
        reader = csv.DictReader(io.StringIO(content.decode("utf8"), newline=""))
        assert reader.fieldnames == fields and not content.startswith(b"\xef\xbb\xbf")
        rows = list(reader)
        if name in {"solution.csv", "answers.csv", "picks.csv", "verdicts.csv"}:
            assert all(next(iter(r.values())).startswith("SYNTHETIC-") for r in rows)
    manifest = client.get(result["files"]["manifest.json"]).json()
    assert manifest["validators"]["cutting_official"]["passed"]
    assert manifest["module_provenance"]["assistant"]["synthetic"] is True
    accepted_id = manifest["export_id"]
    assert manifest["accepted_export_id"] == accepted_id
    with write_transaction(factory) as session:
        failed_retry = enqueue(session, d, "quality", {}, started["run_id"])
        failed_retry.state, failed_retry.created_at = "failed", "2099-01-01T00:00:00+00:00"
    partial = client.post(f"/api/v1/runs/{started['run_id']}/export",
                          headers={"Idempotency-Key": "partial-after-accepted"}).json()
    assert partial["status"] == "partial" and "verdicts.csv" not in partial["files"]
    view = client.get(f"/api/v1/runs/{started['run_id']}").json()["manifest"]
    assert view["accepted_export_id"] == accepted_id and view["accepted_files"] == manifest["files"]
    assert client.get(result["files"]["manifest.json"]).json() == manifest


def test_export_pins_csv_refs_and_provenance_while_validator_waits(client, imported, monkeypatch):
    """PRO-R1: controlled concurrent completion, with explicit synthetic solver outputs."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from glassflow.contracts.platform import RunRequest
    from glassflow.core.jobs import enqueue
    from glassflow.modules.platform import exports
    from glassflow.modules.platform.runs import create_run

    factory = client.app.state.session_factory
    with write_transaction(factory) as session:
        started = create_run(
            session, RunRequest(dataset_id=imported["dataset_id"], modules=["cutting"],
                                config_version="synthetic-pro-r1"),
            client.app.state.services, "pro-r1",
        )
        old = session.get(JobRow, started["job_id"])
        dataset_id, old_id = old.dataset_id, old.id
        rows = [{"part_id": r.public_id, "remnant_id": "NEW", "x_mm": "", "y_mm": "", "rot": ""}
                for r in records(session, dataset_id, "orders")]
        old.state, old.result = "completed", {
            "rows": rows, "validated": True, "plan_id": "synthetic-old", "plan_revision": 1,
            "provenance": {"attempt": "old", "nested": {"model": "synthetic-old"}},
        }
    entered, resume = Event(), Event()

    def paused_validator(*args):
        entered.set()
        assert resume.wait(10), "Test did not release validator"
        return {"passed": True, "fixture": "synthetic format-only validator"}

    monkeypatch.setattr(exports, "official_cutting", paused_validator)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(exports.export_run, factory, started["run_id"],
                             client.app.state.data_dir, client.app.state.services, "pro-r1")
        try:
            assert entered.wait(10)
            # This must commit while validation is paused: no writer-lock across validator.
            with write_transaction(factory) as session:
                new = enqueue(session, dataset_id, "cutting", {}, started["run_id"])
                new.state, new.created_at = "completed", "2099-01-01T00:00:00+00:00"
                new.result = {
                    "rows": list(reversed(rows)), "validated": True,
                    "plan_id": "synthetic-new", "plan_revision": 2,
                    "provenance": {"attempt": "new", "nested": {"model": "synthetic-new"}},
                }
                session.flush()
                new_id = new.id
        finally:
            resume.set()
        first = future.result(timeout=10)
    manifest = client.get(first["files"]["manifest.json"]).json()
    assert client.get(first["files"]["solution.csv"]).content == exports.csv_bytes("solution.csv", rows)
    assert manifest["result_refs"]["cutting"]["job_id"] == old_id
    assert manifest["module_provenance"]["cutting"]["attempt"] == "old"
    second = exports.export_run(factory, started["run_id"], client.app.state.data_dir,
                                client.app.state.services, "pro-r1-next")
    newer = client.get(second["files"]["manifest.json"]).json()
    assert client.get(second["files"]["solution.csv"]).content == exports.csv_bytes("solution.csv", list(reversed(rows)))
    assert newer["result_refs"]["cutting"]["job_id"] == new_id
    assert newer["module_provenance"]["cutting"]["attempt"] == "new"
    assert client.get(first["files"]["manifest.json"]).json() == manifest
