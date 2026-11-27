import json

from glassflow.contracts.crm import RankRequest, ReminderRequest
from glassflow.core.jobs import Handler


def update_kb(client, dataset_id, content, version=0, key="kb"):
    return client.post(
        f"/api/v1/datasets/{dataset_id}/kb",
        data={"expected_version": str(version)},
        files={"file": ("changed-kb.json", content, "application/json")},
        headers={"Idempotency-Key": key},
    )


def test_database_sources_kb_history_and_immutable_contest(client, imported, uploads):
    source_id = imported["dataset_id"]
    original = dict(uploads)["ksm_knowledge_base.json"]
    revised = json.loads(original)
    revised["товары"][0]["цена_за_м2_тг"] = 4501
    changed = json.dumps(revised, ensure_ascii=False).encode("utf8")
    assert update_kb(client, source_id, changed).status_code == 409
    copied = client.post(
        f"/api/v1/datasets/{source_id}/working-copy", json={}, headers={"Idempotency-Key": "working-kb"}
    ).json()
    working = copied["dataset_id"]
    adapter = client.app.state.intelligence_sources
    initial = adapter.knowledge_base(working)
    assert initial.content == original
    metrics = client.get("/api/v1/analytics/managers", params={"dataset_id": working}).json()
    response = update_kb(client, working, changed)
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 1
    assert update_kb(client, working, changed).json() == response.json()
    assert adapter.knowledge_base(working).content == changed
    assert adapter.knowledge_base(working, f"kb-{initial.sha256[:16]}").content == original
    assert adapter.knowledge_base(source_id).content == original
    assert adapter.materials(working).sha256 == imported["source_hashes"]["materials"]
    assert len(adapter.kb_history(working)) == 2
    assert client.get("/api/v1/analytics/managers", params={"dataset_id": working}).json() == metrics
    assert client.get(f"/api/v1/datasets/{working}").json()["source_hashes"] == imported["source_hashes"]
    assert update_kb(client, working, original, version=0, key="stale-kb").status_code == 409
    reverted = update_kb(client, working, original, version=1, key="revert-kb")
    assert reverted.status_code == 200 and reverted.json()["version"] == 2
    assert adapter.knowledge_base(working).content == original
    assert len(adapter.kb_history(working)) == 2
    copy = client.post(
        f"/api/v1/datasets/{working}/working-copy", json={}, headers={"Idempotency-Key": "copy-history"}
    ).json()
    assert adapter.knowledge_base(copy["dataset_id"]).content == original
    assert len(adapter.kb_history(copy["dataset_id"])) == 2


def test_crm_consumer_port_reuses_http_service(client, imported):
    d = imported["dataset_id"]
    port = client.app.state.crm_port
    assert (
        port.rank(RankRequest(dataset_id=d)).model_dump()
        == client.post("/api/v1/crm/rank", json={"dataset_id": d}).json()
    )
    request = ReminderRequest(
        dataset_id=d,
        recipient_client_id="C115",
        source_app_ids=["A0001"],
        subject_type="interest",
        subject_ref="калёное",
        owner="M1",
    )
    first, second = port.draft_reminder(request), port.draft_reminder(request)
    assert first.reminder_id == second.reminder_id
    assert (
        client.get(f"/api/v1/crm/reminders/{first.reminder_id}", params={"dataset_id": d}).json()
        == first.model_dump()
    )


def synthetic_c2_handler(snapshot, context):
    return {
        "dataset_id": snapshot["cutting_snapshot"]["dataset_id"],
        "operation": snapshot["requested_operation"],
    }


def test_c2_requested_submitter_is_durable_and_scope_checked(client, imported):
    import pytest
    from test_jobs import wait_job

    from glassflow.core.errors import AppError

    submitter = client.app.state.job_submitter
    d = imported["dataset_id"]
    payload = {"dataset_id": d, "config": {"workers": 1, "time_limit_seconds": 10}}
    with pytest.raises(AppError) as unavailable:
        submitter.submit("cutting.solve", d, payload)
    assert unavailable.value.status == 503
    client.app.state.coordinator.handlers["cutting"] = Handler(synthetic_c2_handler)
    with pytest.raises(AppError):
        submitter.submit("cutting.solve", d, {"dataset_id": "other"})
    job = submitter.submit("cutting.solve", d, payload)
    result = wait_job(client, job.job_id, {"completed", "failed"})
    assert result["state"] == "completed" and result["result"] == {
        "dataset_id": d,
        "operation": "cutting.solve",
    }
