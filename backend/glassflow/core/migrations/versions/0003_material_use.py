"""Append-only actual-use evidence and semantic dedupe independent of request keys."""

import sqlalchemy as sa
from alembic import op

revision = "0003_material_use"
down_revision = "0002_immutable_history"


def upgrade():
    op.create_table("material_usage",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("dataset_id", sa.String, sa.ForeignKey("datasets.id"), nullable=False, index=True),
        sa.Column("subject_type", sa.String, nullable=False),
        sa.Column("subject_id", sa.String, nullable=False),
        sa.Column("subject_revision", sa.Integer, nullable=False),
        sa.Column("reservation_id", sa.String, nullable=False),
        sa.Column("source_event_ref", sa.String, nullable=False),
        sa.Column("execution_ref", sa.String, nullable=False),
        sa.Column("execution_version", sa.Integer, nullable=False),
        sa.Column("intent_hash", sa.String, nullable=False),
        sa.Column("receipt_hash", sa.String, nullable=False),
        sa.Column("data", sa.JSON, nullable=False),
        sa.Column("created_at", sa.String, nullable=False),
        sa.UniqueConstraint("dataset_id", "subject_type", "subject_id", name="uq_usage_subject"),
        sa.UniqueConstraint("dataset_id", "reservation_id", name="uq_usage_reservation"),
        sa.UniqueConstraint("dataset_id", "source_event_ref", name="uq_usage_source_event"),
        sa.CheckConstraint("subject_type IN ('order','basket')", name="ck_usage_subject_type"),
        sa.CheckConstraint("subject_revision >= 0 AND execution_version >= 0", name="ck_usage_versions"),
    )
    for action in ("UPDATE", "DELETE"):
        op.execute(f"CREATE TRIGGER immutable_material_usage_{action.lower()} BEFORE {action} ON material_usage "
                   "BEGIN SELECT RAISE(ABORT, 'immutable material usage'); END")


def downgrade():
    raise RuntimeError("Restore a verified backup instead of rewriting actual-use history")
