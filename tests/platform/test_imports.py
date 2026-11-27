import hashlib
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import import_dataset
from sqlalchemy import func, select

from glassflow.core.models import DatasetRow, IdempotencyRow, SourceRow
from glassflow.core.uow import idempotent, write_transaction
from glassflow.modules.platform.imports import inspect_files


def test_original_counts_bytes_and_idempotent_snapshot(client, imported, uploads):
    assert imported["row_counts"] == dict(
        materials=8,
        stock=200,
        orders=298,
        questions=18,
        dialogs=8,
        applications=700,
        kb=1,
        distinct_orders=110,
    )
    again = import_dataset(client, uploads, "new-preview")
    assert again["dataset_id"] == imported["dataset_id"]
    with client.app.state.session_factory() as session:
        sources = list(session.scalars(select(SourceRow)))
        assert {s.filename: s.content for s in sources} == dict(uploads)
        assert all(hashlib.sha256(s.content).hexdigest() == s.sha256 for s in sources)
        assert session.scalar(select(func.count()).select_from(DatasetRow)) == 1
    changed = [(n, c.replace(b"R001,", b"R999,")) if n.startswith("stock") else (n, c) for n, c in uploads]
    other = import_dataset(client, changed)
    assert other["dataset_id"] != imported["dataset_id"]
    assert other["source_hashes"]["stock"] != imported["source_hashes"]["stock"]


def test_validation_no_silent_drop_and_utf8_bom(uploads):
    changed = [
        (n, c.replace(b"clear-8,790,590", b"unknown,-790,590") + c.splitlines(keepends=True)[1])
        if n.startswith("stock")
        else (n, c)
        for n, c in uploads
    ]
    _, _, errors, _ = inspect_files(changed)
    assert {e["field"] for e in errors} >= {"material_id", "длина_мм", "remnant_id"}
    assert all({"file", "row", "field", "raw", "reason"} <= e.keys() for e in errors)
    bom = [(n, b"\xef\xbb\xbf" + c) for n, c in uploads]
    _, originals, errors, warnings = inspect_files(bom)
    assert not errors
    assert len(warnings) == 7
    assert all(c.startswith(b"\xef\xbb\xbf") for _, c in originals.values())
    assert not inspect_files([("turkey_" + name, content) for name, content in uploads])[2]


def test_zip_traversal_key_exclusion_and_fixed_references(uploads):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../steal.csv", "secret")
    with pytest.raises(Exception, match="Небезопасное"):
        inspect_files([("input.zip", archive.getvalue())])
    five = [(n, c) for n, c in uploads if n not in {"materials.csv", "ksm_knowledge_base.json"}]
    parsed, _, errors, warnings = inspect_files(five + [("questions_closed_KEY.csv", b"not csv")])
    assert not errors and len(parsed) == 7
    assert any("evaluation" in w for w in warnings)


def test_import_rollback_and_workspace_isolation(client, uploads, services):
    def crash(*args):
        raise RuntimeError("synthetic crash")

    services.import_hooks.append(crash)
    response = client.post("/api/v1/imports/preview", files=[("files", (n, c)) for n, c in uploads]).json()
    failed = client.post(
        f"/api/v1/imports/{response['import_id']}/commit", json={}, headers={"Idempotency-Key": "crash"}
    )
    assert failed.status_code == 500 and "synthetic crash" not in failed.text
    assert client.get("/api/v1/datasets").json() == []
    services.import_hooks.clear()
    original = import_dataset(client, uploads)
    response = client.post(
        f"/api/v1/datasets/{original['dataset_id']}/working-copy",
        json={},
        headers={"Idempotency-Key": "copy"},
    )
    assert response.status_code == 200
    copy = response.json()
    assert copy["mode"] == "workspace" and copy["parent_id"] == original["dataset_id"]
    assert copy["dataset_id"] != original["dataset_id"]
    assert copy["source_hashes"] == original["source_hashes"]


def test_concurrent_idempotency_and_changed_body(client):
    factory = client.app.state.session_factory
    executions = []

    def invoke(_):
        with write_transaction(factory) as session:

            def action():
                executions.append(1)
                return {"sequence": len(executions)}

            return idempotent(session, "synthetic", "test", "same", {"a": 1}, action)

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(invoke, range(8))) == [{"sequence": 1}] * 8
    assert len(executions) == 1
    with pytest.raises(Exception, match="другим запросом"):
        with write_transaction(factory) as session:
            idempotent(session, "synthetic", "test", "same", {"a": 2}, lambda: {})
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(IdempotencyRow)) == 1


def test_local_boundary_and_safe_errors(client):
    response = client.post("/api/v1/imports/preview", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403 and response.json()["code"] == "ORIGIN_FORBIDDEN"
    response = client.get("/api/v1/datasets", headers={"Host": "evil.example"})
    assert response.status_code == 403
    response = client.post("/api/v1/imports/no/commit", json={"unexpected": "secret"})
    assert response.status_code == 422
    assert "secret" not in response.text and response.json()["correlation_id"]
