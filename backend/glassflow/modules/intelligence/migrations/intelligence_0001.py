"""Migration snippet for the intelligence module (owner: Claude 3).

Not an Alembic revision on its own: GPT Pro wraps ``upgrade``/``downgrade`` in the single
shared revision graph (no competing heads). The table definitions mirror
``glassflow.modules.intelligence.models``; ``test_migration_snippet_matches_models`` keeps the
two in sync.
"""

from __future__ import annotations

import sqlalchemy as sa

SNIPPET_ID = "intelligence_0001"
DEPENDS_ON: tuple[str, ...] = ()


def upgrade(op) -> None:
    op.create_table(
        "intel_quote_revision",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_id", sa.String(128), nullable=False),
        sa.Column("quote_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("kb_version", sa.String(64), nullable=False),
        sa.Column("customer_id", sa.String(128), nullable=True),
        sa.Column("request_json", sa.Text, nullable=False),
        sa.Column("quote_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("confirmed_at", sa.String(40), nullable=True),
        sa.Column("confirmed_by", sa.String(128), nullable=True),
        sa.Column("confirm_key", sa.String(128), nullable=True),
        sa.Column("confirm_body_sha256", sa.String(64), nullable=True),
        sa.UniqueConstraint("dataset_id", "quote_id", "revision", name="uq_intel_quote_revision"),
    )
    op.create_index("ix_intel_quote_lookup", "intel_quote_revision", ["dataset_id", "quote_id"])
    op.create_table(
        "intel_mapping_override",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_id", sa.String(128), nullable=False),
        sa.Column("catalog_product_id", sa.String(128), nullable=False),
        sa.Column("material_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("basis", sa.String(500), nullable=False),
        sa.Column("confirmed_by", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("kb_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("dataset_id", "catalog_product_id", "version", name="uq_intel_mapping_version"),
    )
    op.create_table(
        "intel_conversation",
        sa.Column("conversation_id", sa.String(36), primary_key=True),
        sa.Column("dataset_id", sa.String(128), nullable=False, index=True),
        sa.Column("customer_id", sa.String(128), nullable=True),
        sa.Column("context_json", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "intel_turn",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), nullable=False, index=True),
        sa.Column("turn_index", sa.Integer, nullable=False),
        sa.Column("user_text", sa.Text, nullable=False),
        sa.Column("reply_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("conversation_id", "turn_index", name="uq_intel_turn_index"),
    )
    op.create_table(
        "intel_ai_call",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.String(40), nullable=False, index=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_kind", sa.String(32), nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("queue_ms", sa.Integer, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=True),
        sa.Column("output_tokens", sa.Integer, nullable=True),
        sa.Column("thought_tokens", sa.Integer, nullable=True),
        sa.Column("cached_tokens", sa.Integer, nullable=True),
        sa.Column("cost_usd", sa.String(32), nullable=True),
        sa.Column("cost_source", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("cache_hit", sa.Boolean, nullable=False),
    )
    op.create_table(
        "intel_quality_check",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_id", sa.String(128), nullable=False, index=True),
        sa.Column("dialog_id", sa.String(128), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("kb_version", sa.String(64), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("correct", sa.String(32), nullable=True),
        sa.Column("result_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )


def downgrade(op) -> None:
    for table in ["intel_quality_check", "intel_ai_call", "intel_turn", "intel_conversation", "intel_mapping_override"]:
        op.drop_table(table)
    op.drop_index("ix_intel_quote_lookup", table_name="intel_quote_revision")
    op.drop_table("intel_quote_revision")
