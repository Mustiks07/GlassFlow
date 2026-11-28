"""Versioned physical labels and issue sheets never overwrite their evidence."""

from alembic import op

revision = "0006_operational_documents"
down_revision = "0005_execution_history"


def upgrade():
    for action in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER immutable_operational_document_{action.lower()} BEFORE {action} ON platform_objects "
            "WHEN OLD.kind IN ('piece_label','warehouse_document','job_checkpoint') "
            "BEGIN SELECT RAISE(ABORT, 'immutable operational document'); END"
        )


def downgrade():
    raise RuntimeError("Restore a verified backup instead of deleting operational history")
