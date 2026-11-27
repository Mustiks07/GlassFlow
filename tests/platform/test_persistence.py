from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from glassflow.core.uow import write_transaction


def test_immutable_bytes_history_and_dataset_identity_in_sqlite(client, imported):
    factory = client.app.state.session_factory
    for sql in (
        "UPDATE source_records SET data='{}'",
        "DELETE FROM source_files",
        "DELETE FROM audit_events",
        "UPDATE idempotency SET result='{}'",
        "UPDATE datasets SET mode='workspace'",
    ):
        with pytest.raises(IntegrityError):
            with write_transaction(factory) as session:
                session.execute(text(sql))
    assert client.get(f"/api/v1/datasets/{imported['dataset_id']}").json()["mode"] == "source"


def test_concurrent_optimistic_mutations_only_one_commits(client, imported):
    d = imported["dataset_id"]
    body = dict(
        dataset_id=d,
        recipient_client_id="C115",
        source_app_ids=["A0001"],
        subject_type="interest",
        subject_ref="калёное",
        due_at="2026-12-01T12:00:00Z",
        owner="M1",
    )
    reminder = client.post("/api/v1/crm/reminders", json=body, headers={"Idempotency-Key": "new"}).json()
    url = f"/api/v1/crm/reminders/{reminder['reminder_id']}/confirm"

    def confirm(number):
        return client.post(
            url,
            json={"dataset_id": d, "expected_version": 0},
            headers={"Idempotency-Key": f"parallel-{number}"},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(confirm, range(2))) == [200, 409]
