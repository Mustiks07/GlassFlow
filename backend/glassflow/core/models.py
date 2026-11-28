"""Platform persistence; domain services share the metadata and request UoW."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from glassflow.core.db import Base


def uid() -> str:
    return str(uuid4())


def now() -> str:
    return datetime.now(UTC).isoformat()


class DatasetRow(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str]
    mode: Mapped[str]
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("datasets.id"))
    fingerprint: Mapped[str] = mapped_column(index=True)
    version: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[str] = mapped_column(default=now)
    source_hashes: Mapped[dict] = mapped_column(JSON)
    row_counts: Mapped[dict] = mapped_column(JSON)


class SourceRow(Base):
    __tablename__ = "source_files"
    __table_args__ = (UniqueConstraint("dataset_id", "kind"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    kind: Mapped[str]
    filename: Mapped[str]
    sha256: Mapped[str]
    schema_version: Mapped[str] = mapped_column(default="1")
    row_count: Mapped[int]
    imported_at: Mapped[str] = mapped_column(default=now)
    content: Mapped[bytes] = mapped_column(LargeBinary)


class RecordRow(Base):
    """Immutable parsed input; never a second mutable inventory/catalog."""

    __tablename__ = "source_records"
    __table_args__ = (UniqueConstraint("dataset_id", "kind", "public_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    kind: Mapped[str]
    public_id: Mapped[str]
    source_row: Mapped[int]
    data: Mapped[dict] = mapped_column(JSON)


class StagingRow(Base):
    __tablename__ = "import_staging"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    created_at: Mapped[str] = mapped_column(default=now)
    files: Mapped[list] = mapped_column(JSON)
    report: Mapped[dict] = mapped_column(JSON)


class ObjectRow(Base):
    __tablename__ = "platform_objects"
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[int] = mapped_column(default=0)
    data: Mapped[dict] = mapped_column(JSON)


class IdempotencyRow(Base):
    __tablename__ = "idempotency"
    dataset_id: Mapped[str] = mapped_column(String, primary_key=True)
    operation: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str]
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(default=now)


class AuditRow(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[str]
    action: Mapped[str]
    object_id: Mapped[str]
    actor: Mapped[str] = mapped_column(default="local_owner")
    correlation_id: Mapped[str]
    created_at: Mapped[str] = mapped_column(default=now)
    versions: Mapped[dict] = mapped_column(JSON, default=dict)


class JobRow(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(index=True)
    kind: Mapped[str]
    state: Mapped[str] = mapped_column(default="queued", index=True)
    stage: Mapped[str] = mapped_column(default="queued")
    input: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_valid_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None]
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    stopped: Mapped[bool] = mapped_column(default=False)
    completed: Mapped[int] = mapped_column(default=0)
    total: Mapped[int | None]
    created_at: Mapped[str] = mapped_column(default=now)
    started_at: Mapped[str | None]
    finished_at: Mapped[str | None]


class SettingsRow(Base):
    __tablename__ = "settings"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[int] = mapped_column(default=0)
    data: Mapped[dict] = mapped_column(JSON)


class MaterialUseRow(Base):
    """Immutable U06 ledger; inventory remains owned by C2."""
    __tablename__ = "material_usage"
    __table_args__ = (
        UniqueConstraint("dataset_id", "subject_type", "subject_id", name="uq_usage_subject"),
        UniqueConstraint("dataset_id", "reservation_id", name="uq_usage_reservation"),
        UniqueConstraint("dataset_id", "source_event_ref", name="uq_usage_source_event"),
        CheckConstraint("subject_type IN ('order','basket')", name="ck_usage_subject_type"),
        CheckConstraint("subject_revision >= 0 AND execution_version >= 0", name="ck_usage_versions"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    subject_type: Mapped[str]
    subject_id: Mapped[str]
    subject_revision: Mapped[int]
    reservation_id: Mapped[str]
    source_event_ref: Mapped[str]
    execution_ref: Mapped[str]
    execution_version: Mapped[int]
    intent_hash: Mapped[str]
    receipt_hash: Mapped[str]
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(default=now)
