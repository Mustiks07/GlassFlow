"""Intelligence tables on the shared declarative Base (platform DB, no second engine/session).

The foundation creates them via ``create_all``; GPT Pro registers
``migrations/intelligence_0001.py`` in the single Alembic history. Prompts and raw provider
payloads are not stored; the usage ledger keeps sizes, tokens, latency and cost only.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from glassflow.core.db import Base


class QuoteRevisionRow(Base):
    __tablename__ = "intel_quote_revision"
    __table_args__ = (
        UniqueConstraint("dataset_id", "quote_id", "revision", name="uq_intel_quote_revision"),
        Index("ix_intel_quote_lookup", "dataset_id", "quote_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(128))
    quote_id: Mapped[str] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    kb_version: Mapped[str] = mapped_column(String(64))
    customer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_json: Mapped[str] = mapped_column(Text)
    quote_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))
    confirmed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirm_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirm_body_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)


class MappingOverrideRow(Base):
    __tablename__ = "intel_mapping_override"
    __table_args__ = (UniqueConstraint("dataset_id", "catalog_product_id", "version", name="uq_intel_mapping_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(128))
    catalog_product_id: Mapped[str] = mapped_column(String(128))
    material_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    basis: Mapped[str] = mapped_column(String(500))
    confirmed_by: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer)
    kb_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40))


class ConversationRow(Base):
    __tablename__ = "intel_conversation"
    conversation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(128), index=True)
    customer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    context_json: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class TurnRow(Base):
    __tablename__ = "intel_turn"
    __table_args__ = (UniqueConstraint("conversation_id", "turn_index", name="uq_intel_turn_index"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    turn_index: Mapped[int] = mapped_column(Integer)
    user_text: Mapped[str] = mapped_column(Text)
    reply_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class AICallRow(Base):
    __tablename__ = "intel_ai_call"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[str] = mapped_column(String(40), index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    purpose: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(64))
    model_id: Mapped[str] = mapped_column(String(200))
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    error_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    queue_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thought_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cost_source: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(64))
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)


class QualityCheckRow(Base):
    __tablename__ = "intel_quality_check"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(128), index=True)
    dialog_id: Mapped[str] = mapped_column(String(128))
    input_sha256: Mapped[str] = mapped_column(String(64))
    kb_version: Mapped[str] = mapped_column(String(64))
    verdict: Mapped[str] = mapped_column(String(16))
    correct: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


INTELLIGENCE_TABLES = [
    QuoteRevisionRow.__table__,
    MappingOverrideRow.__table__,
    ConversationRow.__table__,
    TurnRow.__table__,
    AICallRow.__table__,
    QualityCheckRow.__table__,
]
