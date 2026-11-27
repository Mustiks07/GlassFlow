"""Immutable platform schema v1, including foundation upgrade."""

import sqlalchemy as sa
from alembic import op

revision = "0001_platform"
down_revision = None


def upgrade():
    # Foundation had just this table, without an Alembic version.
    if "app_metadata" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "app_metadata",
            sa.Column("key", sa.String, primary_key=True),
            sa.Column("value", sa.String, nullable=False),
        )
    op.create_table(
        "datasets",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("mode", sa.String, nullable=False),
        sa.Column("parent_id", sa.String, sa.ForeignKey("datasets.id")),
        sa.Column("fingerprint", sa.String, nullable=False, index=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("created_at", sa.String, nullable=False),
        sa.Column("source_hashes", sa.JSON, nullable=False),
        sa.Column("row_counts", sa.JSON, nullable=False),
    )
    op.create_table(
        "source_files",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("dataset_id", sa.String, sa.ForeignKey("datasets.id"), nullable=False, index=True),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("filename", sa.String, nullable=False),
        sa.Column("sha256", sa.String, nullable=False),
        sa.Column("schema_version", sa.String, nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False),
        sa.Column("imported_at", sa.String, nullable=False),
        sa.Column("content", sa.LargeBinary, nullable=False),
        sa.UniqueConstraint("dataset_id", "kind"),
    )
    op.create_table(
        "source_records",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("dataset_id", sa.String, sa.ForeignKey("datasets.id"), nullable=False, index=True),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("public_id", sa.String, nullable=False),
        sa.Column("source_row", sa.Integer, nullable=False),
        sa.Column("data", sa.JSON, nullable=False),
        sa.UniqueConstraint("dataset_id", "kind", "public_id"),
    )
    op.create_table(
        "import_staging",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("created_at", sa.String, nullable=False),
        sa.Column("files", sa.JSON, nullable=False),
        sa.Column("report", sa.JSON, nullable=False),
    )
    op.create_table(
        "platform_objects",
        sa.Column("dataset_id", sa.String, sa.ForeignKey("datasets.id"), primary_key=True),
        sa.Column("kind", sa.String, primary_key=True),
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("data", sa.JSON, nullable=False),
    )
    op.create_table(
        "idempotency",
        sa.Column("dataset_id", sa.String, primary_key=True),
        sa.Column("operation", sa.String, primary_key=True),
        sa.Column("key", sa.String, primary_key=True),
        sa.Column("request_hash", sa.String, nullable=False),
        sa.Column("result", sa.JSON, nullable=False),
        sa.Column("created_at", sa.String, nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("dataset_id", sa.String, nullable=False),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("object_id", sa.String, nullable=False),
        sa.Column("actor", sa.String, nullable=False),
        sa.Column("correlation_id", sa.String, nullable=False),
        sa.Column("created_at", sa.String, nullable=False),
        sa.Column("versions", sa.JSON, nullable=False),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("dataset_id", sa.String, sa.ForeignKey("datasets.id"), nullable=False, index=True),
        sa.Column("run_id", sa.String, index=True),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("state", sa.String, nullable=False, index=True),
        sa.Column("stage", sa.String, nullable=False),
        sa.Column("input", sa.JSON, nullable=False),
        sa.Column("result", sa.JSON),
        sa.Column("last_valid_result", sa.JSON),
        sa.Column("error_code", sa.String),
        sa.Column("cancel_requested", sa.Boolean, nullable=False),
        sa.Column("stopped", sa.Boolean, nullable=False),
        sa.Column("completed", sa.Integer, nullable=False),
        sa.Column("total", sa.Integer),
        sa.Column("created_at", sa.String, nullable=False),
        sa.Column("started_at", sa.String),
        sa.Column("finished_at", sa.String),
    )
    op.create_table(
        "settings",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("data", sa.JSON, nullable=False),
    )


def downgrade():
    raise RuntimeError("Use a verified backup; destructive schema downgrade is disabled")
