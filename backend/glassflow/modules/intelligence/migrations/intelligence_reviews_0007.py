"""Snippet only: central 0007_intelligence_reviews after 0006_operational_documents.

Importing intelligence.models registers ORM tables on the existing shared Base;
the central Alembic graph must call this upgrade/downgrade once. No second engine.
"""

import sqlalchemy as sa

SNIPPET_ID = "intelligence_reviews_0007"


def upgrade(op):
    op.create_table("intel_review_item",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_id", sa.String(128), nullable=False, index=True),
        sa.Column("kb_version", sa.String(64), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("dataset_id", "fingerprint", name="uq_intel_review_fingerprint"))
    op.create_table("intel_manager_correction",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_id", sa.String(128), nullable=False, index=True),
        sa.Column("dialog_id", sa.String(128), nullable=False),
        sa.Column("kb_version", sa.String(64), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("dataset_id", "dialog_id", "kb_version", "input_sha256", name="uq_intel_correction_input"))


def downgrade(op):
    op.drop_table("intel_manager_correction")
    op.drop_table("intel_review_item")
