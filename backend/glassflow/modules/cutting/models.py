"""SQLAlchemy tables of the cutting/inventory domain (owner: Claude 2).

Registered on the shared ``Base`` so the foundation bootstrap creates them; Pro moves the DDL into the
single Alembic history (see ``migrations/0001_cutting.sql``). Every row is scoped by ``dataset_id``;
the technical UUID is separate from the external CSV ID.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from glassflow.core.db import Base


class CutDataset(Base):
    """Cutting-side registration of a dataset snapshot. Pro's dataset registry stays the authority."""

    __tablename__ = "cut_datasets"
    dataset_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16))  # source | workspace | contest
    mutable: Mapped[bool] = mapped_column(Boolean)
    parent_dataset_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_hash: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[str] = mapped_column(String(40))
    __table_args__ = (CheckConstraint("mode in ('source','workspace','contest')", name="ck_cut_dataset_mode"),)


class CutMaterial(Base):
    __tablename__ = "cut_materials"
    dataset_id: Mapped[str] = mapped_column(ForeignKey("cut_datasets.dataset_id"), primary_key=True)
    material_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    thickness_mm: Mapped[int] = mapped_column(Integer)
    price_per_m2: Mapped[str] = mapped_column(String(32))  # exact decimal string
    tempered: Mapped[bool] = mapped_column(Boolean)


class CutRemnant(Base):
    __tablename__ = "cut_remnants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("cut_datasets.dataset_id"), index=True)
    remnant_id: Mapped[str] = mapped_column(String(128))
    material_id: Mapped[str] = mapped_column(String(128))
    length_mm: Mapped[int] = mapped_column(Integer)
    width_mm: Mapped[int] = mapped_column(Integer)
    age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    defect: Mapped[bool] = mapped_column(Boolean)
    location_raw: Mapped[str] = mapped_column(String(256))
    rack: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cell: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="available")
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    origin: Mapped[str] = mapped_column(String(16), default="source")
    original: Mapped[bool] = mapped_column(Boolean, default=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("cut_remnants.id"), nullable=True)
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
    __table_args__ = (
        UniqueConstraint("dataset_id", "remnant_id", name="uq_cut_remnant_external"),
        CheckConstraint("length_mm > 0 AND width_mm > 0", name="ck_cut_remnant_dims"),
        CheckConstraint("age_days IS NULL OR age_days >= 0", name="ck_cut_remnant_age"),
        CheckConstraint("status in ('available','reserved','consumed','withdrawn')", name="ck_cut_remnant_status"),
        CheckConstraint("origin in ('source','working','child')", name="ck_cut_remnant_origin"),
        CheckConstraint("version >= 0", name="ck_cut_remnant_version"),
        Index("ix_cut_remnant_material_status", "dataset_id", "material_id", "status"),
    )


class CutPart(Base):
    __tablename__ = "cut_parts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("cut_datasets.dataset_id"), index=True)
    part_id: Mapped[str] = mapped_column(String(128))
    order_id: Mapped[str] = mapped_column(String(128))
    material_id: Mapped[str] = mapped_column(String(128))
    length_mm: Mapped[int] = mapped_column(Integer)
    width_mm: Mapped[int] = mapped_column(Integer)
    premium: Mapped[bool] = mapped_column(Boolean)
    product_type: Mapped[str] = mapped_column(String(128), default="")
    seq: Mapped[int] = mapped_column(Integer)  # input row order: the exact output order of solution.csv
    __table_args__ = (
        UniqueConstraint("dataset_id", "part_id", name="uq_cut_part_external"),
        CheckConstraint("length_mm > 0 AND width_mm > 0", name="ck_cut_part_dims"),
    )


class CutPlanRow(Base):
    """One immutable revision of a plan lineage ``plan_id``. Committed revisions never change."""

    __tablename__ = "cut_plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("cut_datasets.dataset_id"), index=True)
    plan_id: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer)
    parent_plan_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    search_status: Mapped[str] = mapped_column(String(24))
    stop_reason: Mapped[str] = mapped_column(String(24), default="completed")
    source: Mapped[str] = mapped_column(String(16), default="solver")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    issues_json: Mapped[str] = mapped_column(Text, default="[]")
    locks_json: Mapped[str] = mapped_column(Text, default="[]")
    """Requested lock constraints of the task (enforced until an explicit edit removes them)."""
    inventory_token: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[str] = mapped_column(String(40))
    committed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    __table_args__ = (
        UniqueConstraint("dataset_id", "plan_id", "revision", name="uq_cut_plan_revision"),
        CheckConstraint(
            "status in ('draft','validated','committed','superseded','invalid')", name="ck_cut_plan_status"
        ),
        # At most one committed (active) plan revision per dataset.
        Index("uq_cut_plan_active", "dataset_id", unique=True, sqlite_where=text("status = 'committed'")),
    )


class CutPlacementRow(Base):
    __tablename__ = "cut_placements"
    plan_row_id: Mapped[str] = mapped_column(ForeignKey("cut_plans.id", ondelete="CASCADE"), primary_key=True)
    part_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    remnant_id: Mapped[str] = mapped_column(String(128))  # external remnant id or NEW
    x_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    y_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lock_kind: Mapped[str] = mapped_column(String(16), default="none")
    seq: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        CheckConstraint("rot IS NULL OR rot in (0,1)", name="ck_cut_placement_rot"),
        CheckConstraint("lock_kind in ('none','assignment','placement')", name="ck_cut_placement_lock"),
    )


class CutReservation(Base):
    """A reservation covers one whole original/working piece and the confirmed layout on it."""

    __tablename__ = "cut_reservations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("cut_datasets.dataset_id"), index=True)
    remnant_row_id: Mapped[str] = mapped_column(ForeignKey("cut_remnants.id"))
    plan_row_id: Mapped[str | None] = mapped_column(ForeignKey("cut_plans.id"), nullable=True)
    """NULL for a whole-piece reservation confirmed from a quote (owner_context = quote:<id>@<revision>)."""
    plan_id: Mapped[str] = mapped_column(String(64))
    plan_revision: Mapped[int] = mapped_column(Integer)
    owner_context: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(16), default="active")
    version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(40))
    released_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    consumed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    __table_args__ = (
        CheckConstraint("status in ('active','released','consumed')", name="ck_cut_reservation_status"),
        # Database-level guard against double reservation of one piece.
        Index("uq_cut_reservation_active", "remnant_row_id", unique=True, sqlite_where=text("status = 'active'")),
    )


class CutAuditEvent(Base):
    __tablename__ = "cut_audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(128), index=True)
    seq: Mapped[int] = mapped_column(Integer, autoincrement=True, index=True)
    action: Mapped[str] = mapped_column(String(64))
    object_type: Mapped[str] = mapped_column(String(32))
    object_id: Mapped[str] = mapped_column(String(128))
    before_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    after_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor: Mapped[str] = mapped_column(String(128), default="local-manager")
    correlation_id: Mapped[str] = mapped_column(String(64))
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(String(40))


class CutIdempotency(Base):
    """Interim module-local idempotency store; Pro's platform service replaces it (same semantics)."""

    __tablename__ = "cut_idempotency"
    dataset_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))
