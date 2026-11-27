"""Enforce append-only source bytes, parsed history, audit and replay in SQLite itself."""

from alembic import op

revision = "0002_immutable_history"
down_revision = "0001_platform"


def upgrade():
    for table in ("source_files", "source_records", "audit_events", "idempotency"):
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER immutable_{table}_{action.lower()} BEFORE {action} ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'immutable history'); END"
            )
    op.execute(
        "CREATE TRIGGER immutable_dataset_identity BEFORE UPDATE OF mode,parent_id,fingerprint,source_hashes,row_counts "
        "ON datasets WHEN NEW.mode IS NOT OLD.mode OR NEW.parent_id IS NOT OLD.parent_id "
        "OR NEW.fingerprint IS NOT OLD.fingerprint OR NEW.source_hashes IS NOT OLD.source_hashes "
        "OR NEW.row_counts IS NOT OLD.row_counts "
        "BEGIN SELECT RAISE(ABORT, 'immutable dataset identity'); END"
    )


def downgrade():
    raise RuntimeError("Restore a verified backup instead of mutating history")
