"""Physical executions and pinned joint selections are immutable evidence."""

from alembic import op

revision = "0005_execution_history"
down_revision = "0004_domains"


def upgrade():
    op.execute("INSERT OR IGNORE INTO idempotency(dataset_id,operation,key,request_hash,result) "
               "SELECT dataset_id,'cutting:' || operation,key,request_hash,response_json FROM cut_idempotency")
    for action in ("UPDATE", "DELETE"):
        op.execute(f"CREATE TRIGGER immutable_cut_artifact_{action.lower()} BEFORE {action} ON platform_objects "
                   "WHEN OLD.kind IN ('cut_execution','cut_selection') "
                   "BEGIN SELECT RAISE(ABORT, 'immutable cutting evidence'); END")


def downgrade():
    raise RuntimeError("Restore a verified backup instead of mutating execution history")
