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


def test_upgrade_from_0002_backs_up_and_preserves_history(tmp_path):
    import sqlite3
    from contextlib import closing
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine

    from glassflow.core import db

    config = Config()
    config.set_main_option("script_location", str(Path(db.__file__).parent / "migrations"))
    original = create_engine(f"sqlite:///{(tmp_path / 'glassflow.db').as_posix()}")
    with original.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0002_immutable_history")
        connection.execute(text("INSERT INTO app_metadata(key,value) VALUES ('synthetic_marker','preserved')"))
    original.dispose()
    engine, factory = db.create_database(tmp_path)
    try:
        with factory() as session:
            assert session.execute(text("SELECT value FROM app_metadata WHERE key='synthetic_marker'")).scalar() == "preserved"
            assert session.execute(text("SELECT version_num FROM alembic_version")).scalar() == db.SCHEMA_HEAD
            assert len(session.execute(text("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='material_usage'")).all()) == 2
        backups = list(tmp_path.glob("pre-migration-*.db"))
        assert len(backups) == 1
        with closing(sqlite3.connect(backups[0])) as backup:
            assert backup.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0002_immutable_history"
            assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert ScriptDirectory.from_config(config).get_heads() == [db.SCHEMA_HEAD]
    finally:
        engine.dispose()
