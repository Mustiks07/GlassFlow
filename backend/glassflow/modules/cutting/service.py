"""Cutting & inventory domain service (owner: Claude 2).

The service receives a SQLAlchemy ``Session`` that belongs to the platform unit of work and NEVER
commits it: the caller owns the transaction boundary (``uow.write_transaction`` until Pro's UoW
lands). Mutations use optimistic versions and compare-and-set UPDATEs, so concurrent confirmations
produce exactly one success even without serialisable isolation; a partial unique index is the
database-level guard against double reservation.

No solver and no LLM call happens inside a write transaction: ``solve_input`` is a short read,
the solver runs in the platform worker, ``store_solver_plan`` is a short write.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from glassflow.contracts.common import Dimensions
from glassflow.contracts.cutting import (
    AuditEvent,
    Candidate,
    Candidates,
    ChildRemnantsRequest,
    CommitPlan,
    CommitResult,
    CompareRequest,
    ConsumeRequest,
    CutMetrics,
    CutPlan,
    DraftRequest,
    DraftResult,
    ExportRow,
    FindRequest,
    FreeRemnant,
    FreeRemnantsCheck,
    ImpactReport,
    ImpactRequest,
    InventoryChange,
    LayoutPart,
    MeasurementUpdate,
    NewRemnant,
    Placement,
    PlacementChange,
    PlanComparison,
    PlanIssue,
    PlanLayout,
    PlanRef,
    PlanSummary,
    ReleaseRequest,
    Remnant,
    RemnantLayout,
    RemnantPage,
    RemnantUpdate,
    Reservation,
    ReserveRequest,
    SolutionExport,
    SolveInput,
    SolverConfig,
    SolveRequest,
    ValidationResult,
    WithdrawRequest,
)

from .conversion import input_from_snapshot, to_placement, to_plan_issue
from .domain import (
    GAP_MM,
    NEW,
    TEMPERED_TOLERANCE_MM,
    TRIM_MM,
    Assignment,
    MaterialSpec,
    PartSpec,
    RemnantSpec,
    Snapshot,
    oriented_size,
)
from .eligibility import REASON_RU, pair_reason
from .geometry import ValidationReport, validate_plan
from .metrics import compute_metrics, exact_value, money
from .models import (
    CutAuditEvent,
    CutDataset,
    CutMaterial,
    CutPart,
    CutPlacementRow,
    CutPlanRow,
    CutRemnant,
    CutReservation,
)
from .packing import Item, MaxRectsBin
from .source_io import SOLUTION_HEADER, solution_rows

ACTOR = "local-manager"


class CuttingError(Exception):
    def __init__(self, status: int, code: str, message_ru: str, *, conflict_objects: list[str] | None = None,
                 field_errors: list[dict[str, str]] | None = None, retryable: bool = False):
        super().__init__(f"{code}: {message_ru}")
        self.status = status
        self.code = code
        self.message_ru = message_ru
        self.conflict_objects = conflict_objects or []
        self.field_errors = field_errors or []
        self.retryable = retryable


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


_LOCATION = re.compile(r"стеллаж\s*([^\s,;]+)\s*[,;]?\s*ячейка\s*([^\s,;]+)", re.IGNORECASE)


def parse_location(raw: str) -> tuple[str | None, str | None]:
    """Recognise «Стеллаж A, ячейка 1». Unrecognised text stays only in ``location_raw``."""
    match = _LOCATION.search(raw or "")
    return (match.group(1), match.group(2)) if match else (None, None)


def _request_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass(slots=True)
class LoadedPlan:
    row: CutPlanRow
    assignments: list[Assignment]
    snapshot: Snapshot = field(repr=False)


class CuttingService:
    def __init__(self, session: Session, *, actor: str = ACTOR, correlation_id: str | None = None):
        self.session = session
        self.actor = actor
        self.correlation_id = correlation_id or str(uuid.uuid4())

    # ================================================================== dataset registration (Pro)
    def register_dataset(self, dataset_id: str, mode: str, snapshot: Snapshot, *, parent_dataset_id: str | None = None,
                         source_hash: str = "") -> None:
        """Persist an imported snapshot. Called by the platform import commit inside its transaction."""
        if self.session.get(CutDataset, dataset_id) is not None:
            raise CuttingError(409, "DATASET_EXISTS", f"Набор {dataset_id} уже зарегистрирован в раскрое.")
        if mode not in {"source", "workspace", "contest"}:
            raise CuttingError(422, "BAD_MODE", "mode: source | workspace | contest")
        stamp = now()
        self.session.add(CutDataset(dataset_id=dataset_id, mode=mode, mutable=mode == "workspace",
                                    parent_dataset_id=parent_dataset_id, source_hash=source_hash, created_at=stamp))
        self.session.flush()
        for m in snapshot.materials.values():
            self.session.add(CutMaterial(dataset_id=dataset_id, material_id=m.material_id, name=m.name,
                                         thickness_mm=m.thickness_mm, price_per_m2=str(m.price_per_m2),
                                         tempered=m.tempered))
        for index, rid in enumerate(snapshot.remnant_order):
            r = snapshot.remnants[rid]
            rack, cell = parse_location(r.location_raw)
            self.session.add(CutRemnant(
                id=str(uuid.uuid4()), dataset_id=dataset_id, remnant_id=rid, material_id=r.material_id,
                length_mm=r.length_mm, width_mm=r.width_mm, age_days=r.age_days, defect=r.defect,
                location_raw=r.location_raw, rack=rack, cell=cell, status=r.status, version=r.version,
                origin="source" if r.original else "working", original=r.original, source_row=index + 2,
                created_at=stamp, updated_at=stamp))
        for index, pid in enumerate(snapshot.part_order):
            p = snapshot.parts[pid]
            self.session.add(CutPart(id=str(uuid.uuid4()), dataset_id=dataset_id, part_id=pid, order_id=p.order_id,
                                     material_id=p.material_id, length_mm=p.length_mm, width_mm=p.width_mm,
                                     premium=p.premium, product_type=p.product_type, seq=index))
        self.session.flush()
        self._audit(dataset_id, "dataset.registered", "dataset", dataset_id, None, None,
                    {"mode": mode, "remnants": len(snapshot.remnants), "parts": len(snapshot.parts)})

    def create_working_copy(self, source_dataset_id: str, new_dataset_id: str) -> None:
        """Workspace copy of a snapshot: same external IDs, new internal IDs, isolated history."""
        source = self._dataset(source_dataset_id)
        snapshot = self.load_snapshot(source_dataset_id, current_state=False)
        self.register_dataset(new_dataset_id, "workspace", snapshot, parent_dataset_id=source.dataset_id,
                              source_hash=source.source_hash)

    def _dataset(self, dataset_id: str) -> CutDataset:
        ds = self.session.get(CutDataset, dataset_id)
        if ds is None:
            raise CuttingError(404, "DATASET_NOT_FOUND", f"Набор данных {dataset_id} не найден.")
        return ds

    def _require_mutable(self, dataset_id: str) -> CutDataset:
        ds = self._dataset(dataset_id)
        if not ds.mutable:
            raise CuttingError(409, "IMMUTABLE_DATASET",
                               "Исходный или конкурсный снимок неизменяем. Создайте рабочую копию.",
                               conflict_objects=[dataset_id])
        return ds

    # ================================================================== snapshot
    def load_snapshot(self, dataset_id: str, *, current_state: bool = True) -> Snapshot:
        self._dataset(dataset_id)
        materials = {
            m.material_id: MaterialSpec(m.material_id, m.tempered, Decimal(m.price_per_m2), m.name, m.thickness_mm)
            for m in self.session.scalars(select(CutMaterial).where(CutMaterial.dataset_id == dataset_id))
        }
        remnant_rows = self.session.scalars(
            select(CutRemnant).where(CutRemnant.dataset_id == dataset_id).order_by(
                CutRemnant.source_row.is_(None), CutRemnant.source_row, CutRemnant.created_at, CutRemnant.remnant_id)
        ).all()
        remnants = {}
        for r in remnant_rows:
            if not current_state and r.origin != "source":
                continue
            remnants[r.remnant_id] = RemnantSpec(
                r.remnant_id, r.material_id, r.length_mm, r.width_mm, r.defect, r.age_days,
                r.status if current_state else "available", r.version if current_state else 0,
                r.location_raw, r.original)
        parts = {
            p.part_id: PartSpec(p.part_id, p.order_id, p.material_id, p.length_mm, p.width_mm, p.premium,
                                p.product_type)
            for p in self.session.scalars(select(CutPart).where(CutPart.dataset_id == dataset_id).order_by(CutPart.seq))
        }
        return Snapshot(dataset_id, materials, remnants, parts, list(parts), list(remnants))

    def inventory_token(self, dataset_id: str) -> str:
        total = self.session.scalar(
            select(func.coalesce(func.sum(CutRemnant.version), 0)).where(CutRemnant.dataset_id == dataset_id))
        count = self.session.scalar(select(func.count()).select_from(CutRemnant).where(
            CutRemnant.dataset_id == dataset_id))
        return f"{count}:{total}"

    # ================================================================== remnants
    def _remnant_row(self, dataset_id: str, remnant_id: str) -> CutRemnant:
        row = self.session.scalar(select(CutRemnant).where(CutRemnant.dataset_id == dataset_id,
                                                           CutRemnant.remnant_id == remnant_id))
        if row is None:
            raise CuttingError(404, "REMNANT_NOT_FOUND", f"Остаток {remnant_id} не найден в наборе {dataset_id}.")
        return row

    def _active_reservation(self, remnant_row_id: str) -> CutReservation | None:
        return self.session.scalar(select(CutReservation).where(CutReservation.remnant_row_id == remnant_row_id,
                                                                CutReservation.status == "active"))

    def _remnant_dto(self, row: CutRemnant) -> Remnant:
        reservation = self._active_reservation(row.id) if row.status == "reserved" else None
        parent = self.session.get(CutRemnant, row.parent_id) if row.parent_id else None
        return Remnant(dataset_id=row.dataset_id, remnant_id=row.remnant_id, material_id=row.material_id,
                       dimensions=Dimensions(length_mm=row.length_mm, width_mm=row.width_mm), age_days=row.age_days,
                       defect=row.defect, location_raw=row.location_raw, status=row.status, version=row.version,
                       internal_id=row.id, origin=row.origin, original=row.original, rack=row.rack, cell=row.cell,
                       parent_remnant_id=parent.remnant_id if parent else None,
                       active_reservation_id=reservation.id if reservation else None, status_reason=row.status_reason)

    def get_remnant(self, dataset_id: str, remnant_id: str) -> Remnant:
        return self._remnant_dto(self._remnant_row(dataset_id, remnant_id))

    SORTS = {
        "remnant_id": CutRemnant.remnant_id, "area": CutRemnant.length_mm * CutRemnant.width_mm,
        "age_days": CutRemnant.age_days, "material_id": CutRemnant.material_id, "status": CutRemnant.status,
        "source_order": CutRemnant.source_row,
    }

    def list_remnants(self, dataset_id: str, *, material_id: str | None = None, status: str | None = None,
                      defect: bool | None = None, original: bool | None = None, min_length_mm: int | None = None,
                      min_width_mm: int | None = None, search: str | None = None, sort: str = "source_order",
                      descending: bool = False, limit: int = 50, offset: int = 0) -> RemnantPage:
        self._dataset(dataset_id)
        if not 1 <= limit <= 200:
            raise CuttingError(422, "BAD_LIMIT", "limit должен быть от 1 до 200.")
        if sort not in self.SORTS:
            raise CuttingError(422, "BAD_SORT", f"Сортировка допускает: {', '.join(self.SORTS)}.")
        query = select(CutRemnant).where(CutRemnant.dataset_id == dataset_id)
        if material_id:
            query = query.where(CutRemnant.material_id == material_id)
        if status:
            query = query.where(CutRemnant.status == status)
        if defect is not None:
            query = query.where(CutRemnant.defect == defect)
        if original is not None:
            query = query.where(CutRemnant.original == original)
        if min_length_mm is not None or min_width_mm is not None:
            a, b = min_length_mm or 0, min_width_mm or 0
            big, small = max(a, b), min(a, b)
            query = query.where(func.max(CutRemnant.length_mm, CutRemnant.width_mm) >= big,
                                func.min(CutRemnant.length_mm, CutRemnant.width_mm) >= small)
        if search:
            like = f"%{search}%"
            query = query.where(CutRemnant.remnant_id.like(like) | CutRemnant.location_raw.like(like))
        total = self.session.scalar(select(func.count()).select_from(query.subquery()))
        column = self.SORTS[sort]
        order = column.desc() if descending else column.asc()
        rows = self.session.scalars(query.order_by(order, CutRemnant.remnant_id).limit(limit).offset(offset)).all()
        return RemnantPage(items=[self._remnant_dto(r) for r in rows], total=total or 0, limit=limit, offset=offset)

    def add_remnant(self, request: NewRemnant) -> Remnant:
        self._require_mutable(request.dataset_id)
        material = self.session.get(CutMaterial, (request.dataset_id, request.material_id))
        if material is None:
            raise CuttingError(422, "UNKNOWN_MATERIAL", f"Материал {request.material_id} отсутствует в materials.",
                               field_errors=[{"field": "material_id", "message": "unknown"}])
        remnant_id = request.remnant_id or self._next_working_id(request.dataset_id)
        if remnant_id.upper() == NEW:
            raise CuttingError(422, "RESERVED_ID", "ID NEW зарезервирован.")
        exists = self.session.scalar(select(CutRemnant.id).where(CutRemnant.dataset_id == request.dataset_id,
                                                                 CutRemnant.remnant_id == remnant_id))
        if exists:
            raise CuttingError(409, "DUPLICATE_REMNANT_ID", f"Остаток {remnant_id} уже есть в наборе.",
                               conflict_objects=[remnant_id])
        stamp = now()
        rack, cell = parse_location(request.location_raw)
        row = CutRemnant(id=str(uuid.uuid4()), dataset_id=request.dataset_id, remnant_id=remnant_id,
                         material_id=request.material_id, length_mm=request.dimensions.length_mm,
                         width_mm=request.dimensions.width_mm, age_days=request.age_days, defect=request.defect,
                         location_raw=request.location_raw, rack=rack, cell=cell, status="available", version=0,
                         origin="working", original=False, created_at=stamp, updated_at=stamp)
        self.session.add(row)
        self.session.flush()
        self._audit(request.dataset_id, "remnant.added", "remnant", remnant_id, None, 0,
                    {"length_mm": row.length_mm, "width_mm": row.width_mm, "material_id": row.material_id,
                     "age_known": request.age_days is not None})
        return self._remnant_dto(row)

    def _next_working_id(self, dataset_id: str) -> str:
        count = self.session.scalar(select(func.count()).select_from(CutRemnant).where(
            CutRemnant.dataset_id == dataset_id, CutRemnant.origin != "source")) or 0
        while True:
            count += 1
            candidate = f"W{count:04d}"
            if not self.session.scalar(select(CutRemnant.id).where(CutRemnant.dataset_id == dataset_id,
                                                                   CutRemnant.remnant_id == candidate)):
                return candidate

    def _cas(self, row: CutRemnant, expected_version: int, allowed: set[str], **values) -> None:
        """Compare-and-set: bump version only if the stored version and status still match."""
        try:
            result = self.session.execute(
                update(CutRemnant)
                .where(CutRemnant.id == row.id, CutRemnant.version == expected_version,
                       CutRemnant.status.in_(allowed))
                .values(version=expected_version + 1, updated_at=now(), **values)
                .execution_options(synchronize_session=False))
        except OperationalError as exc:  # SQLITE_BUSY after a concurrent writer committed
            raise CuttingError(409, "CONCURRENT_UPDATE", "Остаток изменен параллельной операцией; обновите данные.",
                               conflict_objects=[row.remnant_id], retryable=True) from exc
        if result.rowcount != 1:
            self.session.refresh(row)
            raise CuttingError(
                409, "VERSION_CONFLICT",
                f"Остаток {row.remnant_id}: ожидалась версия {expected_version} и статус {sorted(allowed)}, "
                f"фактически версия {row.version}, статус {row.status}.",
                conflict_objects=[row.remnant_id])
        self.session.refresh(row)

    def update_remnant(self, remnant_id: str, request: RemnantUpdate) -> Remnant:
        self._require_mutable(request.dataset_id)
        row = self._remnant_row(request.dataset_id, remnant_id)
        values: dict = {}
        if request.location_raw is not None:
            values["location_raw"] = request.location_raw
            values["rack"], values["cell"] = parse_location(request.location_raw)
        if request.defect is not None:
            values["defect"] = request.defect
        if request.age_days is not None:
            values["age_days"] = request.age_days
        if not values:
            raise CuttingError(422, "NOTHING_TO_UPDATE", "Не указано ни одно изменяемое поле.")
        if "defect" in values and values["defect"] and row.status == "reserved":
            # Premium parts may be placed on this piece: changing the defect flag must re-check the layout.
            raise CuttingError(409, "RESERVED_LAYOUT_AFFECTED",
                               "Остаток зарезервирован: изменение дефекта требует освобождения и пересчета.",
                               conflict_objects=[remnant_id])
        before = row.version
        self._cas(row, request.expected_version, {"available", "reserved", "withdrawn"}, **values)
        self._audit(request.dataset_id, "remnant.updated", "remnant", remnant_id, before, row.version,
                    {k: v for k, v in values.items() if isinstance(v, (str, int, bool)) or v is None}
                    | {"reason": request.reason})
        return self._remnant_dto(row)

    def update_measurement(self, remnant_id: str, request: MeasurementUpdate) -> tuple[Remnant, ImpactReport]:
        self._require_mutable(request.dataset_id)
        row = self._remnant_row(request.dataset_id, remnant_id)
        if request.previous_dimensions is not None and (
            request.previous_dimensions.length_mm, request.previous_dimensions.width_mm
        ) != (row.length_mm, row.width_mm):
            raise CuttingError(409, "PREVIOUS_MEASUREMENT_MISMATCH",
                               f"Введенный прежний размер не совпадает с сохраненным {row.length_mm}×{row.width_mm}.",
                               conflict_objects=[remnant_id])
        if row.status == "consumed":
            raise CuttingError(409, "REMNANT_CONSUMED", "Списанный остаток нельзя перемерить.", conflict_objects=[remnant_id])
        impact = self.impact(ImpactRequest(dataset_id=request.dataset_id, remnant_id=remnant_id,
                                           change="measurement", dimensions=request.dimensions))
        before = (row.length_mm, row.width_mm, row.version)
        self._cas(row, request.expected_version, {"available", "reserved", "withdrawn"},
                  length_mm=request.dimensions.length_mm, width_mm=request.dimensions.width_mm)
        self._audit(request.dataset_id, "remnant.measured", "remnant", remnant_id, before[2], row.version,
                    {"before": f"{before[0]}x{before[1]}", "after": f"{row.length_mm}x{row.width_mm}",
                     "reason": request.reason, "affected_parts": impact.affected_part_ids})
        impact.remnant_version = row.version
        return self._remnant_dto(row), impact

    def withdraw(self, remnant_id: str, request: WithdrawRequest) -> InventoryChange:
        """available -> withdrawn (exclusion, broken, sold outside). Reserved pieces must be released first."""
        self._require_mutable(request.dataset_id)
        row = self._remnant_row(request.dataset_id, remnant_id)
        if row.status == "reserved":
            raise CuttingError(409, "REMNANT_RESERVED", "Остаток зарезервирован; сначала освободите резерв.",
                               conflict_objects=[remnant_id])
        before = row.version
        self._cas(row, request.expected_version, {"available"}, status="withdrawn", status_reason=request.reason)
        event = self._audit(request.dataset_id, "remnant.withdrawn", "remnant", remnant_id, before, row.version,
                            {"reason": request.reason})
        return InventoryChange(remnant=self._remnant_dto(row), audit_event_id=event)

    def restore(self, remnant_id: str, request: ReleaseRequest) -> InventoryChange:
        """withdrawn -> available (correcting an exclusion). Consumed pieces are never restored."""
        self._require_mutable(request.dataset_id)
        row = self._remnant_row(request.dataset_id, remnant_id)
        before = row.version
        self._cas(row, request.expected_version, {"withdrawn"}, status="available", status_reason=None)
        event = self._audit(request.dataset_id, "remnant.restored", "remnant", remnant_id, before, row.version,
                            {"reason": request.reason})
        return InventoryChange(remnant=self._remnant_dto(row), audit_event_id=event)

    def reserve(self, remnant_id: str, request: ReserveRequest) -> InventoryChange:
        """available -> reserved for one confirmed request. Re-reads availability; stale UI text cannot reserve.

        The whole piece is reserved (never an independent reservation per part). A piece used by the
        committed plan is refused: that requires a joint replan and an explicit plan commit.
        """
        self._require_mutable(request.dataset_id)
        row = self._remnant_row(request.dataset_id, remnant_id)
        snapshot = self.load_snapshot(request.dataset_id)
        remnant = snapshot.remnants[remnant_id]
        part = PartSpec("__request__", request.owner_context, request.material_id, request.dimensions.length_mm,
                        request.dimensions.width_mm, request.premium)
        if request.material_id not in snapshot.materials:
            raise CuttingError(422, "UNKNOWN_MATERIAL", f"Материал {request.material_id} отсутствует в materials.")
        reason = pair_reason(snapshot, part, remnant)
        if reason is not None:
            raise CuttingError(409, reason, REASON_RU.get(reason, reason), conflict_objects=[remnant_id])
        active = self._active_plan_row(request.dataset_id)
        if active is not None and any(a.remnant_id == remnant_id for a in self._assignments(active)):
            raise CuttingError(409, "OCCUPIED", REASON_RU["OCCUPIED"], conflict_objects=[remnant_id])
        if request.x_mm is not None or request.y_mm is not None or request.rot is not None:
            probe = Snapshot(snapshot.dataset_id, snapshot.materials, {remnant_id: remnant}, {"__request__": part})
            report = validate_plan(probe, [Assignment("__request__", remnant_id, request.x_mm, request.y_mm,
                                                      request.rot)])
            if not report.valid:
                raise CuttingError(422, report.issues[0].code, report.issues[0].message_ru, conflict_objects=[remnant_id])
        before = row.version
        self._cas(row, request.expected_version, {"available"}, status="reserved", status_reason=None)
        res = CutReservation(id=str(uuid.uuid4()), dataset_id=request.dataset_id, remnant_row_id=row.id,
                             plan_row_id=None, plan_id="", plan_revision=0, owner_context=request.owner_context,
                             status="active", version=0, created_at=now())
        self.session.add(res)
        try:
            self.session.flush()
        except IntegrityError as exc:
            raise CuttingError(409, "DOUBLE_RESERVATION", "Остаток уже зарезервирован.", retryable=True) from exc
        event = self._audit(request.dataset_id, "remnant.reserved", "remnant", remnant_id, before, row.version,
                            {"reservation_id": res.id, "owner_context": request.owner_context})
        return InventoryChange(remnant=self._remnant_dto(row), reservation=self._reservation_dto(res),
                               audit_event_id=event)

    def _reservation_dto(self, res: CutReservation) -> Reservation:
        remnant = self.session.get(CutRemnant, res.remnant_row_id)
        part_ids: list[str] = []
        if res.plan_row_id:
            part_ids = list(self.session.scalars(select(CutPlacementRow.part_id).where(
                CutPlacementRow.plan_row_id == res.plan_row_id, CutPlacementRow.remnant_id == remnant.remnant_id
            ).order_by(CutPlacementRow.seq)))
        return Reservation(reservation_id=res.id, dataset_id=res.dataset_id, remnant_id=remnant.remnant_id,
                           plan_id=res.plan_id, plan_revision=res.plan_revision, owner_context=res.owner_context,
                           status=res.status, version=res.version, created_at=res.created_at,
                           released_at=res.released_at, consumed_at=res.consumed_at, part_ids=part_ids)

    def _reservation(self, dataset_id: str, reservation_id: str) -> CutReservation:
        res = self.session.get(CutReservation, reservation_id)
        if res is None or res.dataset_id != dataset_id:
            raise CuttingError(404, "RESERVATION_NOT_FOUND", f"Резерв {reservation_id} не найден в наборе.")
        return res

    def consume(self, remnant_id: str, request: ConsumeRequest) -> InventoryChange:
        """reserved -> consumed for the whole piece and its confirmed layout. Not undoable by release."""
        self._require_mutable(request.dataset_id)
        row = self._remnant_row(request.dataset_id, remnant_id)
        res = self._reservation(request.dataset_id, request.reservation_id)
        if res.remnant_row_id != row.id or res.status != "active":
            raise CuttingError(409, "RESERVATION_NOT_ACTIVE",
                               f"Резерв {res.id} не активен для остатка {remnant_id} (статус {res.status}).",
                               conflict_objects=[remnant_id, res.id])
        before = row.version
        self._cas(row, request.expected_version, {"reserved"}, status="consumed", status_reason=request.reason)
        res.status = "consumed"
        res.consumed_at = now()
        res.version += 1
        self.session.flush()
        event = self._audit(request.dataset_id, "remnant.consumed", "remnant", remnant_id, before, row.version,
                            {"reservation_id": res.id, "plan_id": res.plan_id, "reason": request.reason})
        return InventoryChange(remnant=self._remnant_dto(row), reservation=self._reservation_dto(res),
                               audit_event_id=event)

    def release_reservation(self, reservation_id: str, request: ReleaseRequest) -> InventoryChange:
        """reserved -> available before production. ``expected_version`` is the reservation version."""
        self._require_mutable(request.dataset_id)
        res = self._reservation(request.dataset_id, reservation_id)
        if res.status != "active":
            raise CuttingError(409, "RESERVATION_NOT_ACTIVE",
                               "Резерв уже освобожден или израсходован; расход отменяется только корректирующей операцией.",
                               conflict_objects=[reservation_id])
        if res.version != request.expected_version:
            raise CuttingError(409, "VERSION_CONFLICT", f"Версия резерва {res.version}, ожидалась {request.expected_version}.",
                               conflict_objects=[reservation_id])
        row = self.session.get(CutRemnant, res.remnant_row_id)
        before = row.version
        self._cas(row, row.version, {"reserved"}, status="available", status_reason=None)
        res.status = "released"
        res.released_at = now()
        res.version += 1
        self.session.flush()
        event = self._audit(request.dataset_id, "remnant.released", "remnant", row.remnant_id, before, row.version,
                            {"reservation_id": res.id, "reason": request.reason})
        return InventoryChange(remnant=self._remnant_dto(row), reservation=self._reservation_dto(res),
                               audit_event_id=event)

    def release_remnant(self, remnant_id: str, request: ReleaseRequest) -> InventoryChange:
        """Same as releasing the active reservation; ``expected_version`` is the remnant version here."""
        row = self._remnant_row(request.dataset_id, remnant_id)
        res = self._active_reservation(row.id)
        if row.status == "consumed":
            raise CuttingError(409, "REMNANT_CONSUMED", "Израсходованный остаток нельзя вернуть обычным освобождением.",
                               conflict_objects=[remnant_id])
        if res is None:
            raise CuttingError(409, "NOT_RESERVED", "Остаток не зарезервирован.", conflict_objects=[remnant_id])
        if row.version != request.expected_version:
            raise CuttingError(409, "VERSION_CONFLICT", f"Версия остатка {row.version}, ожидалась {request.expected_version}.",
                               conflict_objects=[remnant_id])
        return self.release_reservation(res.id, ReleaseRequest(dataset_id=request.dataset_id,
                                                               expected_version=res.version, reason=request.reason))

    def add_children(self, remnant_id: str, request: ChildRemnantsRequest) -> InventoryChange:
        """Record real child pieces after consumption. They are working stock, never original contest stock."""
        self._require_mutable(request.dataset_id)
        row = self._remnant_row(request.dataset_id, remnant_id)
        if row.status != "consumed":
            raise CuttingError(409, "PARENT_NOT_CONSUMED", "Дочерние остатки учитываются только после расхода куска.",
                               conflict_objects=[remnant_id])
        if row.version != request.expected_version:
            raise CuttingError(409, "VERSION_CONFLICT", "Версия родительского остатка изменилась.",
                               conflict_objects=[remnant_id])
        children = []
        for child in request.children:
            if child.dimensions.length_mm * child.dimensions.width_mm > row.length_mm * row.width_mm or max(
                child.dimensions.length_mm, child.dimensions.width_mm) > max(row.length_mm, row.width_mm):
                raise CuttingError(422, "CHILD_TOO_LARGE", "Дочерний кусок не может быть больше исходного.")
            dto = self.add_remnant(NewRemnant(dataset_id=request.dataset_id, material_id=row.material_id,
                                              dimensions=child.dimensions, defect=row.defect,
                                              location_raw=child.location_raw, age_days=row.age_days,
                                              remnant_id=child.remnant_id))
            child_row = self._remnant_row(request.dataset_id, dto.remnant_id)
            child_row.origin = "child"
            child_row.parent_id = row.id
            self.session.flush()
            children.append(self._remnant_dto(child_row))
        event = self._audit(request.dataset_id, "remnant.children_recorded", "remnant", remnant_id, row.version,
                            row.version, {"children": [c.remnant_id for c in children]})
        return InventoryChange(remnant=self._remnant_dto(row), audit_event_id=event, children=children)

    # ================================================================== audit / events
    def _audit(self, dataset_id: str, action: str, object_type: str, object_id: str, before: int | None,
               after: int | None, details: dict) -> str:
        seq = (self.session.scalar(select(func.max(CutAuditEvent.seq))) or 0) + 1
        event_id = str(uuid.uuid4())
        self.session.add(CutAuditEvent(id=event_id, dataset_id=dataset_id, seq=seq, action=action,
                                       object_type=object_type, object_id=object_id, before_version=before,
                                       after_version=after, actor=self.actor, correlation_id=self.correlation_id,
                                       details_json=json.dumps(details, ensure_ascii=False, default=str),
                                       created_at=now()))
        self.session.flush()
        return event_id

    def events(self, dataset_id: str, *, object_id: str | None = None, after_seq: int = 0,
               limit: int = 200) -> list[AuditEvent]:
        """Versioned change feed for stale sale cards / reminders (Pro) and remnant history (UI)."""
        query = select(CutAuditEvent).where(CutAuditEvent.dataset_id == dataset_id, CutAuditEvent.seq > after_seq)
        if object_id:
            query = query.where(CutAuditEvent.object_id == object_id)
        rows = self.session.scalars(query.order_by(CutAuditEvent.seq).limit(min(limit, 1000))).all()
        return [AuditEvent(event_id=r.id, dataset_id=r.dataset_id, action=r.action, object_type=r.object_type,
                           object_id=r.object_id, before_version=r.before_version, after_version=r.after_version,
                           actor=r.actor, correlation_id=r.correlation_id, created_at=r.created_at,
                           details={"seq": r.seq, **json.loads(r.details_json)}) for r in rows]

    # ================================================================== idempotency (interim)
    def idempotent(self, dataset_id: str, operation: str, key: str | None, payload: dict, action):
        """Same key + same body -> stored result; same key + other body -> 409. Stored in the same transaction."""
        if not key:
            return action()
        from glassflow.core.models import IdempotencyRow
        digest = _request_hash(payload)
        scope = "cutting:" + operation
        stored = self.session.get(IdempotencyRow, (dataset_id, scope, key))
        if stored is not None:
            if stored.request_hash != digest:
                raise CuttingError(409, "IDEMPOTENCY_KEY_REUSED",
                                   "Этот Idempotency-Key уже использован с другим телом запроса.")
            return stored.result
        result = action()
        body = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        self.session.add(IdempotencyRow(dataset_id=dataset_id, operation=scope, key=key,
                                        request_hash=digest, result=body))
        self.session.flush()
        return body

    # ================================================================== plans: storage and reading
    def _active_plan_row(self, dataset_id: str) -> CutPlanRow | None:
        return self.session.scalar(select(CutPlanRow).where(CutPlanRow.dataset_id == dataset_id,
                                                            CutPlanRow.status == "committed"))

    def _plan_row(self, dataset_id: str, plan_id: str, revision: int | None = None) -> CutPlanRow:
        query = select(CutPlanRow).where(CutPlanRow.dataset_id == dataset_id, CutPlanRow.plan_id == plan_id)
        if revision is not None:
            query = query.where(CutPlanRow.revision == revision)
        row = self.session.scalar(query.order_by(CutPlanRow.revision.desc()).limit(1))
        if row is None:
            raise CuttingError(404, "PLAN_NOT_FOUND", f"План {plan_id} (ревизия {revision}) не найден в наборе {dataset_id}.")
        return row

    def _assignments(self, row: CutPlanRow) -> list[Assignment]:
        return [Assignment(p.part_id, p.remnant_id, p.x_mm, p.y_mm, p.rot, p.lock_kind)
                for p in self.session.scalars(select(CutPlacementRow).where(
                    CutPlacementRow.plan_row_id == row.id).order_by(CutPlacementRow.seq))]

    def _unavailable_for(self, dataset_id: str, plan_row: CutPlanRow | None, snapshot: Snapshot) -> set[str]:
        """Pieces this plan cannot use: consumed/withdrawn, or reserved by somebody other than the active plan."""
        result = {rid for rid, r in snapshot.remnants.items() if r.status in {"consumed", "withdrawn"}}
        active = self._active_plan_row(dataset_id)
        for res, remnant_id in self.session.execute(
            select(CutReservation, CutRemnant.remnant_id).join(CutRemnant, CutRemnant.id == CutReservation.remnant_row_id)
            .where(CutReservation.dataset_id == dataset_id, CutReservation.status == "active")
        ):
            owned_by_active = active is not None and res.plan_row_id == active.id
            if not owned_by_active:
                result.add(remnant_id)
        return result

    def _validation_snapshot(self, snapshot: Snapshot) -> Snapshot:
        """For validation, reserved pieces are judged by reservation ownership, not by status text."""
        remnants = {rid: (RemnantSpec(r.remnant_id, r.material_id, r.length_mm, r.width_mm, r.defect, r.age_days,
                                      "available", r.version, r.location_raw, r.original)
                          if r.status == "reserved" else r) for rid, r in snapshot.remnants.items()}
        return Snapshot(snapshot.dataset_id, snapshot.materials, remnants, snapshot.parts, snapshot.part_order,
                        snapshot.remnant_order)

    @staticmethod
    def _locks_of(row: CutPlanRow | None) -> list[Assignment]:
        if row is None:
            return []
        return [Assignment(d["part_id"], d["remnant_id"], d.get("x_mm"), d.get("y_mm"), d.get("rot"), d["lock_kind"])
                for d in json.loads(row.locks_json or "[]")]

    @staticmethod
    def _locks_json(locks: list[Assignment]) -> str:
        return json.dumps([{"part_id": a.part_id, "remnant_id": a.remnant_id, "x_mm": a.x_mm, "y_mm": a.y_mm,
                            "rot": a.rot, "lock_kind": a.lock_kind} for a in locks if a.lock_kind != "none"],
                          ensure_ascii=False)

    def _validate(self, dataset_id: str, plan_row: CutPlanRow | None, assignments: list[Assignment],
                  snapshot: Snapshot, requested_locks: list[Assignment] | None = None) -> ValidationReport:
        """Validate against the current stock AND every requested lock of the revision (C2-F1)."""
        unavailable = self._unavailable_for(dataset_id, plan_row, snapshot)
        requested = self._locks_of(plan_row) if requested_locks is None else requested_locks
        locks = requested + [a for a in assignments if a.lock_kind != "none"]
        return validate_plan(self._validation_snapshot(snapshot), assignments, unavailable_remnant_ids=unavailable,
                             locks=locks)

    def _plan_dto(self, row: CutPlanRow, assignments: list[Assignment] | None = None,
                  report: ValidationReport | None = None) -> CutPlan:
        assignments = assignments if assignments is not None else self._assignments(row)
        metrics = CutMetrics.model_validate(json.loads(row.metrics_json))
        free = json.loads(row.evidence_json).get("free_original_remnant_ids", "")
        issues = [to_plan_issue(i) for i in report.issues] if report is not None else [
            PlanIssue.model_validate(i) for i in json.loads(row.issues_json)
        ]
        evidence = {k: v for k, v in json.loads(row.evidence_json).items()
                    if isinstance(v, (str, int, float, bool)) or v is None}
        evidence.pop("free_original_remnant_ids", None)
        return CutPlan(dataset_id=row.dataset_id, plan_id=row.plan_id, revision=row.revision, status=row.status,
                       placements=[to_placement(a) for a in assignments], metrics=metrics,
                       free_original_remnant_ids=[x for x in free.split(",") if x],
                       search_status=row.search_status, parent_plan_id=row.parent_plan_id,
                       parent_revision=row.parent_revision, stop_reason=row.stop_reason,
                       config=SolverConfig.model_validate(json.loads(row.config_json)) if row.config_json != "{}" else None,
                       issues=issues, evidence=evidence, created_at=row.created_at, source=row.source,
                       requested_locks=[to_placement(a) for a in self._locks_of(row)],
                       inventory_version=row.inventory_token,
                       inventory_current=row.inventory_token == self.inventory_token(row.dataset_id))

    def _store_revision(self, dataset_id: str, plan_id: str, assignments: list[Assignment], *, source: str,
                        status_if_valid: str, search_status: str, stop_reason: str, config: SolverConfig | None,
                        parent: CutPlanRow | None, evidence: dict, new_reasons: dict[str, str] | None = None,
                        requested_locks: list[Assignment] | None = None, extra_issues: list[PlanIssue] | None = None
                        ) -> tuple[CutPlanRow, ValidationReport]:
        snapshot = self.load_snapshot(dataset_id)
        by_part = {a.part_id: a for a in assignments}
        if len(by_part) != len(assignments):
            raise CuttingError(422, "DUPLICATE_PART", "В плане есть повторяющиеся part_id.")
        requested = self._locks_of(parent) if requested_locks is None else requested_locks
        report = self._validate(dataset_id, parent, assignments, snapshot, requested)
        if new_reasons is None:
            new_reasons = {pid: "NOT_PLACED_BY_EDIT" for pid in report.new_part_ids}
        metrics, free = compute_metrics(snapshot, report, new_reasons)
        revision = (self.session.scalar(select(func.max(CutPlanRow.revision)).where(
            CutPlanRow.dataset_id == dataset_id, CutPlanRow.plan_id == plan_id)) or 0) + 1 if parent else 1
        if parent is not None and parent.plan_id != plan_id:
            revision = 1
        row = CutPlanRow(
            id=str(uuid.uuid4()), dataset_id=dataset_id, plan_id=plan_id, revision=revision,
            parent_plan_id=parent.plan_id if parent else None, parent_revision=parent.revision if parent else None,
            status=status_if_valid if report.valid else "invalid", search_status=search_status,
            stop_reason=stop_reason, source=source,
            config_json=config.model_dump_json() if config else "{}", metrics_json=metrics.model_dump_json(),
            evidence_json=json.dumps({**evidence, "free_original_remnant_ids": ",".join(free)}, ensure_ascii=False),
            issues_json=json.dumps([to_plan_issue(i).model_dump() for i in report.issues]
                                   + [i.model_dump() for i in (extra_issues or [])], ensure_ascii=False),
            locks_json=self._locks_json(requested),
            inventory_token=self.inventory_token(dataset_id), created_at=now())
        self.session.add(row)
        self.session.flush()
        order = {pid: i for i, pid in enumerate(snapshot.part_order)}
        for a in assignments:
            self.session.add(CutPlacementRow(plan_row_id=row.id, part_id=a.part_id, remnant_id=a.remnant_id,
                                             x_mm=a.x_mm, y_mm=a.y_mm, rot=a.rot, lock_kind=a.lock_kind,
                                             seq=order.get(a.part_id, len(order))))
        self.session.flush()
        self._audit(dataset_id, f"plan.{source}", "plan", f"{plan_id}@{revision}", None, revision,
                    {"status": row.status, "coverage_percent": metrics.coverage_percent,
                     "invalid": metrics.invalid, "missing": metrics.missing})
        return row, report

    def store_solver_plan(self, dataset_id: str, plan: CutPlan, *, base_plan_id: str | None = None) -> CutPlan:
        """Coordinator entry point: persist a worker result as a NEW draft/validated revision.

        It never commits a plan and never replaces the active one (TZ 9, 13).
        """
        if plan.dataset_id != dataset_id:
            raise CuttingError(422, "DATASET_MISMATCH", "Результат расчета относится к другому набору данных.")
        parent = None
        plan_id = f"plan-{uuid.uuid4().hex[:12]}"
        if base_plan_id:
            parent = self._plan_row(dataset_id, base_plan_id)
            plan_id = parent.plan_id
        assignments = [Assignment(p.part_id, p.remnant_id, p.x_mm, p.y_mm, p.rot, p.lock_kind) for p in plan.placements]
        # The worker's own status is never trusted: the task's requested locks are re-applied here (C2-F1).
        requested = [Assignment(p.part_id, p.remnant_id, p.x_mm, p.y_mm, p.rot, p.lock_kind)
                     for p in plan.requested_locks]
        solver_conflicts = [i for i in plan.issues if i.code == "LOCK_CONFLICT"]
        row, report = self._store_revision(
            dataset_id, plan_id, assignments, source="solver", status_if_valid="validated",
            search_status=plan.search_status, stop_reason=plan.stop_reason, config=plan.config, parent=parent,
            evidence=dict(plan.evidence), new_reasons=dict(plan.metrics.new_reasons), requested_locks=requested,
            extra_issues=solver_conflicts)
        return self._plan_dto(row, assignments)

    def import_plan(self, dataset_id: str, rows: list[dict[str, str]]) -> CutPlan:
        """Store an uploaded solution.csv as an editable draft after strict parsing (never trusted)."""
        from .geometry import parse_solution_rows

        assignments, issues = parse_solution_rows(rows)
        if issues:
            raise CuttingError(422, "BAD_SOLUTION_ROWS", "; ".join(i.message_ru for i in issues[:10]))
        snapshot = self.load_snapshot(dataset_id)
        tempered_fixed = []
        for a in assignments:
            r = snapshot.remnants.get(a.remnant_id)
            if r and snapshot.is_tempered(r.material_id) and a.x_mm is None:
                from .geometry import canonical_tempered

                part = snapshot.parts.get(a.part_id)
                canon = canonical_tempered(part, r) if part else None
                tempered_fixed.append(canon or a)
            else:
                tempered_fixed.append(a)
        row, report = self._store_revision(dataset_id, f"plan-{uuid.uuid4().hex[:12]}", tempered_fixed,
                                           source="import", status_if_valid="draft", search_status="feasible",
                                           stop_reason="completed", config=None, parent=None, evidence={},
                                           requested_locks=[])
        return self._plan_dto(row, tempered_fixed, report)

    def get_plan(self, dataset_id: str, plan_id: str, revision: int | None = None) -> CutPlan:
        return self._plan_dto(self._plan_row(dataset_id, plan_id, revision))

    def active_plan(self, dataset_id: str) -> CutPlan | None:
        row = self._active_plan_row(dataset_id)
        return self._plan_dto(row) if row else None

    def list_plans(self, dataset_id: str, limit: int = 50) -> list[PlanSummary]:
        self._dataset(dataset_id)
        rows = self.session.scalars(select(CutPlanRow).where(CutPlanRow.dataset_id == dataset_id)
                                    .order_by(CutPlanRow.created_at.desc()).limit(min(limit, 200))).all()
        out = []
        for r in rows:
            m = json.loads(r.metrics_json)
            out.append(PlanSummary(plan_id=r.plan_id, revision=r.revision, status=r.status,
                                   search_status=r.search_status, coverage=m.get("coverage", 0.0),
                                   covered_area_mm2=m.get("covered_area_mm2", 0), created_at=r.created_at,
                                   source=r.source))
        return out

    # ================================================================== editor
    def draft(self, plan_id: str, request: DraftRequest) -> DraftResult:
        """Apply edits to a revision and save a NEW revision. A committed revision is never changed in place."""
        base = self._plan_row(request.dataset_id, plan_id, request.base_revision)
        latest = self._plan_row(request.dataset_id, plan_id)
        if latest.revision != base.revision and base.status != "committed":
            raise CuttingError(409, "STALE_REVISION",
                               f"Редактируется ревизия {base.revision}, последняя {latest.revision}.",
                               conflict_objects=[f"{plan_id}@{latest.revision}"])
        snapshot = self.load_snapshot(request.dataset_id)
        assignments = {a.part_id: a for a in self._assignments(base)}
        requested = {a.part_id: a for a in self._locks_of(base)}
        for edit in request.edits:
            current = assignments.get(edit.part_id)
            if current is None:
                raise CuttingError(422, "UNKNOWN_PART", f"Детали {edit.part_id} нет в плане.")
            lock = requested.get(edit.part_id)
            kind = lock.lock_kind if lock else current.lock_kind
            if edit.action == "unplace":
                if kind != "none":
                    raise CuttingError(409, "PART_LOCKED", f"Деталь {edit.part_id} закреплена; снимите закрепление.")
                assignments[edit.part_id] = Assignment(edit.part_id, NEW)
            elif edit.action == "move":
                locked_remnant = lock.remnant_id if lock else current.remnant_id
                if kind == "placement" or (kind == "assignment" and edit.remnant_id not in (None, locked_remnant)):
                    raise CuttingError(409, "PART_LOCKED", f"Деталь {edit.part_id} закреплена; снимите закрепление.")
                target = edit.remnant_id or current.remnant_id
                if target == NEW:
                    assignments[edit.part_id] = Assignment(edit.part_id, NEW)
                    continue
                x, y, rot = edit.x_mm, edit.y_mm, edit.rot
                remnant = snapshot.remnants.get(target)
                if remnant is not None and snapshot.is_tempered(remnant.material_id) and x is None:
                    x, y = 0, 0
                    part = snapshot.parts[edit.part_id]
                    from .domain import tempered_orientation

                    rot = tempered_orientation(part, remnant) if rot is None else rot
                assignments[edit.part_id] = Assignment(edit.part_id, target, x, y, rot, current.lock_kind)
            elif edit.action == "lock":
                if current.remnant_id == NEW:
                    raise CuttingError(422, "LOCK_ON_NEW", "Нельзя закрепить деталь без остатка (NEW).")
                new_kind = edit.lock_kind or "placement"
                assignments[edit.part_id] = Assignment(current.part_id, current.remnant_id, current.x_mm,
                                                       current.y_mm, current.rot, new_kind)
                requested[edit.part_id] = assignments[edit.part_id]
            elif edit.action == "unlock":
                # Explicit removal of the constraint: the only way a requested lock stops being enforced.
                assignments[edit.part_id] = Assignment(current.part_id, current.remnant_id, current.x_mm,
                                                       current.y_mm, current.rot, "none")
                requested.pop(edit.part_id, None)
        ordered = [assignments[pid] for pid in snapshot.part_order if pid in assignments]
        row, report = self._store_revision(
            request.dataset_id, plan_id, ordered, source="edit", status_if_valid="draft",
            search_status=base.search_status if base.source == "solver" else "feasible", stop_reason=base.stop_reason,
            config=SolverConfig.model_validate(json.loads(base.config_json)) if base.config_json != "{}" else None,
            parent=base, evidence={"edited_from_revision": base.revision, "edits": len(request.edits)},
            requested_locks=list(requested.values()))
        return DraftResult(plan=self._plan_dto(row, ordered, report), validation=self._validation_dto(report, row))

    def _validation_dto(self, report: ValidationReport, row: CutPlanRow | None = None) -> ValidationResult:
        return ValidationResult(valid=report.valid, errors=[i.as_text() for i in report.issues],
                                invalid_part_ids=report.invalid_part_ids, missing_part_ids=report.missing_part_ids,
                                issues=[to_plan_issue(i) for i in report.issues],
                                plan_revision=row.revision if row else None)

    def validate(self, dataset_id: str, plan_id: str, revision: int | None = None) -> ValidationResult:
        """Re-validate a revision against the CURRENT inventory; draft -> validated / invalid."""
        row = self._plan_row(dataset_id, plan_id, revision)
        snapshot = self.load_snapshot(dataset_id)
        report = self._validate(dataset_id, row, self._assignments(row), snapshot)
        if row.status in {"draft", "validated", "invalid"}:
            row.status = "validated" if report.valid else "invalid"
            row.issues_json = json.dumps([to_plan_issue(i).model_dump() for i in report.issues], ensure_ascii=False)
            self.session.flush()
        return self._validation_dto(report, row)

    # ================================================================== commit (atomic reserve)
    def commit(self, plan_id: str, request: CommitPlan) -> CommitResult:
        """One short write transaction: versions, availability, full validity, reservations, audit."""
        self._require_mutable(request.dataset_id)
        row = self._plan_row(request.dataset_id, plan_id, request.plan_revision)
        if row.status == "committed":
            raise CuttingError(409, "PLAN_ALREADY_COMMITTED", "Эта ревизия уже подтверждена.",
                               conflict_objects=[f"{plan_id}@{row.revision}"])
        if row.status in {"superseded", "invalid"}:
            raise CuttingError(409, "PLAN_NOT_COMMITTABLE", f"Ревизия в статусе {row.status} не может быть подтверждена.",
                               conflict_objects=[f"{plan_id}@{row.revision}"])
        snapshot = self.load_snapshot(request.dataset_id)
        assignments = self._assignments(row)
        used = sorted({a.remnant_id for a in assignments if a.remnant_id != NEW})
        conflicts = []
        for rid in used:
            remnant = snapshot.remnants.get(rid)
            expected = request.expected_remnant_versions.get(rid)
            if remnant is None or expected is None or expected != remnant.version:
                conflicts.append(rid)
        if conflicts:
            raise CuttingError(409, "VERSION_CONFLICT",
                               "Версии остатков изменились или не переданы: " + ", ".join(conflicts),
                               conflict_objects=conflicts)
        report = self._validate(request.dataset_id, row, assignments, snapshot)
        if not report.valid:
            codes = sorted({i.code for i in report.issues})
            unavailable = sorted({i.remnant_id for i in report.issues if i.code == "REMNANT_UNAVAILABLE" and i.remnant_id})
            raise CuttingError(409, "PLAN_INVALID", "План недопустим для текущего склада: " + ", ".join(codes),
                               conflict_objects=unavailable or [i.part_id or "" for i in report.issues[:20]])
        active = self._active_plan_row(request.dataset_id)
        released: list[str] = []
        stamp = now()
        if active is not None:
            active.status = "superseded"
            self.session.flush()
            for res in self.session.scalars(select(CutReservation).where(CutReservation.plan_row_id == active.id,
                                                                         CutReservation.status == "active")).all():
                remnant = self.session.get(CutRemnant, res.remnant_row_id)
                res.status = "released"
                res.released_at = stamp
                res.version += 1
                released.append(res.id)
                if remnant.remnant_id not in used:
                    self._cas(remnant, remnant.version, {"reserved"}, status="available")
                    self._audit(request.dataset_id, "remnant.released", "remnant", remnant.remnant_id,
                                remnant.version - 1, remnant.version, {"reservation_id": res.id,
                                                                       "reason": "superseded_plan"})
                else:
                    # Transferred to the new plan below; keep reserved, the reservation id changes.
                    self.session.flush()
        reservations = []
        try:
            for rid in used:
                remnant = self._remnant_row(request.dataset_id, rid)
                expected = request.expected_remnant_versions[rid]
                allowed = {"available"} if remnant.status == "available" else {"reserved"}
                if remnant.status == "reserved":
                    still = self._active_reservation(remnant.id)
                    if still is not None:  # reserved by someone else (quote/other) -> conflict
                        raise CuttingError(409, "REMNANT_RESERVED", f"Остаток {rid} зарезервирован другим действием.",
                                           conflict_objects=[rid])
                self._cas(remnant, expected, allowed, status="reserved", status_reason=None)
                res = CutReservation(id=str(uuid.uuid4()), dataset_id=request.dataset_id, remnant_row_id=remnant.id,
                                     plan_row_id=row.id, plan_id=row.plan_id, plan_revision=row.revision,
                                     owner_context=request.owner_context, status="active", version=0, created_at=stamp)
                self.session.add(res)
                self.session.flush()
                reservations.append(res)
                self._audit(request.dataset_id, "remnant.reserved", "remnant", rid, expected, remnant.version,
                            {"reservation_id": res.id, "plan": f"{row.plan_id}@{row.revision}"})
        except IntegrityError as exc:
            raise CuttingError(409, "DOUBLE_RESERVATION", "Остаток уже зарезервирован параллельной операцией.",
                               retryable=True) from exc
        row.status = "committed"
        row.committed_at = stamp
        try:
            self.session.flush()
        except IntegrityError as exc:
            raise CuttingError(409, "CONCURRENT_COMMIT", "Параллельно подтвержден другой план.", retryable=True) from exc
        self._audit(request.dataset_id, "plan.committed", "plan", f"{row.plan_id}@{row.revision}", None, row.revision,
                    {"reservations": len(reservations), "superseded": f"{active.plan_id}@{active.revision}" if active else None})
        return CommitResult(plan=self._plan_dto(row, assignments, report),
                            reservations=[self._reservation_dto(r) for r in reservations],
                            released_reservation_ids=released,
                            superseded_plan=f"{active.plan_id}@{active.revision}" if active else None)

    # ================================================================== solver input
    def solve_input(self, request: SolveRequest) -> SolveInput:
        """Short read: serialisable snapshot for the platform worker (no transaction kept open)."""
        snapshot = self.load_snapshot(request.dataset_id)
        active = self._active_plan_row(request.dataset_id)
        base = self._plan_row(request.dataset_id, request.base_plan_id) if request.base_plan_id else active
        unavailable = self._unavailable_for(request.dataset_id, None, snapshot) | set(request.excluded_remnant_ids)
        unknown = [r for r in request.excluded_remnant_ids if r not in snapshot.remnants]
        if unknown:
            raise CuttingError(422, "UNKNOWN_REMNANT", "Неизвестные остатки: " + ", ".join(unknown))
        occupied: list[str] = []
        locks = list(request.locks)
        previous: list[Placement] = []
        if base is not None:
            previous = [to_placement(a) for a in self._assignments(base) if a.remnant_id != NEW]
        if request.mode == "keep_committed":
            if active is None:
                raise CuttingError(409, "NO_COMMITTED_PLAN", "Нет подтвержденного плана для режима без перестройки.")
            kept = [a for a in self._assignments(active) if a.remnant_id != NEW]
            occupied = sorted({a.remnant_id for a in kept})
            locked = {lk.part_id for lk in locks}
            locks += [Placement(part_id=a.part_id, remnant_id=a.remnant_id, x_mm=a.x_mm, y_mm=a.y_mm, rot=a.rot,
                                lock_kind="placement") for a in kept if a.part_id not in locked]
            unavailable -= set(occupied)
        for lk in locks:
            if lk.part_id not in snapshot.parts:
                raise CuttingError(422, "UNKNOWN_PART", f"Закрепление для неизвестной детали {lk.part_id}.")
        return input_from_snapshot(
            snapshot, locks=locks, config=request.config, unavailable_remnant_ids=sorted(unavailable),
            occupied_remnant_ids=occupied, previous_placements=previous,
            base_plan_id=base.plan_id if base else None, base_revision=base.revision if base else None)

    # ================================================================== comparison / impact
    def compare(self, request: CompareRequest) -> PlanComparison:
        base_row = self._plan_row(request.dataset_id, request.base.plan_id, request.base.revision)
        cand_row = self._plan_row(request.dataset_id, request.candidate.plan_id, request.candidate.revision)
        base_m = CutMetrics.model_validate(json.loads(base_row.metrics_json))
        cand_m = CutMetrics.model_validate(json.loads(cand_row.metrics_json))
        before = {a.part_id: a for a in self._assignments(base_row)}
        after = {a.part_id: a for a in self._assignments(cand_row)}
        changes = []
        for pid in dict.fromkeys(list(before) + list(after)):
            b, a = before.get(pid), after.get(pid)
            b_new = b is None or b.remnant_id == NEW
            a_new = a is None or a.remnant_id == NEW
            if b_new and a_new:
                continue
            if b_new:
                kind = "added"
            elif a_new:
                kind = "removed"
            elif b.remnant_id != a.remnant_id:
                kind = "reassigned"
            elif (b.x_mm, b.y_mm, b.rot) != (a.x_mm, a.y_mm, a.rot):
                kind = "moved"
            else:
                continue
            changes.append(PlacementChange(part_id=pid, before=to_placement(b) if b else None,
                                           after=to_placement(a) if a else None, kind=kind))
        reserved = {r for (r,) in self.session.execute(
            select(CutRemnant.remnant_id).where(CutRemnant.dataset_id == request.dataset_id,
                                                CutRemnant.status == "reserved"))}
        touched = {c.before.remnant_id for c in changes if c.before} | {c.after.remnant_id for c in changes if c.after}
        return PlanComparison(
            dataset_id=request.dataset_id, base=PlanRef(plan_id=base_row.plan_id, revision=base_row.revision),
            candidate=PlanRef(plan_id=cand_row.plan_id, revision=cand_row.revision),
            delta_covered_area_mm2=cand_m.covered_area_mm2 - base_m.covered_area_mm2,
            delta_coverage=cand_m.coverage - base_m.coverage,
            delta_value_tg=money(Decimal(cand_m.replacement_value_tg) - Decimal(base_m.replacement_value_tg)),
            delta_fully_covered_orders=cand_m.fully_covered_orders - base_m.fully_covered_orders,
            delta_free_original_remnants=cand_m.free_original_remnants - base_m.free_original_remnants,
            newly_new_part_ids=[c.part_id for c in changes if c.kind == "removed"],
            newly_covered_part_ids=[c.part_id for c in changes if c.kind == "added"],
            changes=changes, affected_reserved_remnant_ids=sorted(touched & reserved))

    def impact(self, request: ImpactRequest) -> ImpactReport:
        """What-if of excluding / re-measuring a piece against a plan. Changes nothing (no replacement)."""
        snapshot = self.load_snapshot(request.dataset_id)
        remnant = snapshot.remnants.get(request.remnant_id)
        if remnant is None:
            raise CuttingError(404, "REMNANT_NOT_FOUND", f"Остаток {request.remnant_id} не найден.")
        row = (self._plan_row(request.dataset_id, request.plan_id) if request.plan_id
               else self._active_plan_row(request.dataset_id))
        if request.change == "measurement" and request.dimensions is None:
            raise CuttingError(422, "DIMENSIONS_REQUIRED", "Для нового замера нужны размеры.")
        if row is None:
            return ImpactReport(dataset_id=request.dataset_id, remnant_id=request.remnant_id,
                                remnant_version=remnant.version, plan_id=None, plan_revision=None,
                                affected_part_ids=[], new_part_ids=[], delta_covered_area_mm2=0,
                                delta_value_tg="0.00", affected_reservation_ids=[], affected_order_ids=[],
                                requires_commit=False, note_ru="Нет плана, зависящего от этого остатка.")
        assignments = self._assignments(row)
        on_piece = [a for a in assignments if a.remnant_id == request.remnant_id]
        if request.change == "exclude":
            broken = {a.part_id for a in on_piece}
        else:
            changed = RemnantSpec(remnant.remnant_id, remnant.material_id, request.dimensions.length_mm,
                                  request.dimensions.width_mm, remnant.defect, remnant.age_days, "available",
                                  remnant.version, remnant.location_raw, remnant.original)
            what_if = Snapshot(snapshot.dataset_id, snapshot.materials, {**snapshot.remnants, remnant.remnant_id: changed},
                               snapshot.parts, snapshot.part_order, snapshot.remnant_order)
            rows = [a for a in assignments if a.remnant_id == request.remnant_id]
            report = validate_plan(what_if, rows, require_complete=False)
            broken = set(report.invalid_part_ids)
        covered = {a.part_id: a.remnant_id for a in on_piece if a.part_id in broken}
        area = sum(snapshot.parts[p].area for p in covered)
        value, _ = exact_value(snapshot, covered)
        reservations = [r.id for r in self.session.scalars(select(CutReservation).join(
            CutRemnant, CutRemnant.id == CutReservation.remnant_row_id).where(
            CutRemnant.dataset_id == request.dataset_id, CutRemnant.remnant_id == request.remnant_id,
            CutReservation.status == "active"))]
        return ImpactReport(
            dataset_id=request.dataset_id, remnant_id=request.remnant_id, remnant_version=remnant.version,
            plan_id=row.plan_id, plan_revision=row.revision, affected_part_ids=sorted(broken),
            new_part_ids=sorted(broken), delta_covered_area_mm2=-area, delta_value_tg=money(-value),
            affected_reservation_ids=reservations,
            affected_order_ids=sorted({snapshot.parts[p].order_id for p in broken}),
            requires_commit=bool(broken),
            note_ru=("Затронутые детали станут NEW в текущем плане. Прежний план активен до подтверждения "
                     "нового; пересчет может покрыть их другими кусками." if broken else
                     "Изменение не затрагивает размещения плана."))

    # ================================================================== layout / export
    def layout(self, dataset_id: str, plan_id: str, revision: int | None = None) -> PlanLayout:
        row = self._plan_row(dataset_id, plan_id, revision)
        snapshot = self.load_snapshot(dataset_id)
        groups: dict[str, list[Assignment]] = defaultdict(list)
        new_ids = []
        for a in self._assignments(row):
            (new_ids.append(a.part_id) if a.remnant_id == NEW else groups[a.remnant_id].append(a))
        remnants = []
        for rid in snapshot.remnant_order:
            if rid not in groups:
                continue
            r = snapshot.remnants[rid]
            tempered = snapshot.is_tempered(r.material_id)
            rack, cell = parse_location(r.location_raw)
            parts = []
            for a in groups[rid]:
                p = snapshot.parts.get(a.part_id)
                if p is None:
                    continue
                rot = a.rot or 0
                w, h = oriented_size(p, rot)
                parts.append(LayoutPart(part_id=p.part_id, order_id=p.order_id, x_mm=a.x_mm or 0, y_mm=a.y_mm or 0,
                                        w_mm=w, h_mm=h, rot=rot, lock_kind=a.lock_kind, premium=p.premium))
            remnants.append(RemnantLayout(
                remnant_id=rid, material_id=r.material_id, length_mm=r.length_mm, width_mm=r.width_mm,
                trim_mm=0 if tempered else TRIM_MM, gap_mm=0 if tempered else GAP_MM, tempered=tempered,
                tempered_tolerance_mm=TEMPERED_TOLERANCE_MM, defect=r.defect, location_raw=r.location_raw,
                rack=rack, cell=cell, parts=parts, used_area_mm2=sum(x.w_mm * x.h_mm for x in parts)))
        return PlanLayout(plan_id=row.plan_id, revision=row.revision, remnants=remnants, new_part_ids=new_ids)

    def _live_free(self, row: CutPlanRow, snapshot: Snapshot, report: ValidationReport):
        """Metrics and fully free ORIGINAL pieces of this revision against the stock read in ``snapshot``."""
        stored = CutMetrics.model_validate(json.loads(row.metrics_json))
        metrics, free = compute_metrics(snapshot, report, stored.new_reasons)
        config = SolverConfig.model_validate(json.loads(row.config_json)) if row.config_json != "{}" else None
        minimum = config.minimum_free_remnants if config else 5
        minimum = min(minimum, sum(1 for r in snapshot.remnants.values() if r.original))
        historical = [x for x in json.loads(row.evidence_json).get("free_original_remnant_ids", "").split(",") if x]
        live = set(free)
        gone = [rid for rid in historical if rid not in live]
        return metrics, free, minimum, historical, gone

    def export(self, dataset_id: str, plan_id: str, revision: int | None = None) -> SolutionExport:
        """LIVE export (C2-F2): validation, metrics and free pieces come from ONE read of the current stock."""
        row = self._plan_row(dataset_id, plan_id, revision)
        snapshot = self.load_snapshot(dataset_id)
        token = self.inventory_token(dataset_id)
        as_of = now()
        assignments = self._assignments(row)
        report = self._validate(dataset_id, row, assignments, snapshot)
        if row.status in {"invalid", "superseded"} or not report.valid:
            codes = sorted({i.code for i in report.issues}) or [row.status.upper()]
            raise CuttingError(409, "PLAN_INVALID", "Строгий экспорт заблокирован: " + ", ".join(codes),
                               conflict_objects=[i.as_text() for i in report.issues[:20]])
        rows = solution_rows(snapshot, {a.part_id: a for a in assignments})
        metrics, free, minimum, historical, gone = self._live_free(row, snapshot, report)
        return SolutionExport(dataset_id=dataset_id, plan_id=row.plan_id, revision=row.revision,
                              header=SOLUTION_HEADER, rows=[ExportRow(**r) for r in rows], metrics=metrics,
                              free_original_remnant_ids=free, validation=self._validation_dto(report, row),
                              as_of=as_of, inventory_version=token, plan_inventory_version=row.inventory_token,
                              inventory_changed_since_plan=token != row.inventory_token,
                              plan_free_original_remnant_ids=historical, no_longer_free_remnant_ids=gone,
                              minimum_free_remnants=minimum, minimum_free_remnants_met=len(free) >= minimum)

    def free_remnants(self, dataset_id: str, plan_id: str, revision: int | None = None) -> FreeRemnantsCheck:
        """Final re-check before a sale card / confirmation: fully free original pieces of the plan, now."""
        row = self._plan_row(dataset_id, plan_id, revision)
        snapshot = self.load_snapshot(dataset_id)
        token = self.inventory_token(dataset_id)
        report = self._validate(dataset_id, row, self._assignments(row), snapshot)
        _, free, minimum, historical, gone = self._live_free(row, snapshot, report)
        items = [FreeRemnant(remnant_id=r.remnant_id, version=r.version, material_id=r.material_id,
                             dimensions=Dimensions(length_mm=r.length_mm, width_mm=r.width_mm), defect=r.defect,
                             location_raw=r.location_raw) for r in (snapshot.remnants[x] for x in free)]
        valid_now = report.valid and row.status not in {"invalid", "superseded"}
        return FreeRemnantsCheck(dataset_id=dataset_id, plan_id=row.plan_id, revision=row.revision,
                                 plan_status=row.status if valid_now else "invalid", as_of=now(),
                                 inventory_version=token, free_original=items, count=len(items),
                                 minimum_free_remnants=minimum, minimum_free_remnants_met=len(items) >= minimum,
                                 plan_free_original_remnant_ids=historical, no_longer_free_remnant_ids=gone)

    # ================================================================== fast candidate search
    def new_requirements(self, dataset_id: str, plan_id: str, revision: int | None = None):
        from .insights import new_requirements

        exported = self.export(dataset_id, plan_id, revision)
        row = self._plan_row(dataset_id, plan_id, revision)
        active = self._active_plan_row(dataset_id)
        return new_requirements(self.load_snapshot(dataset_id), self._assignments(row), exported.metrics.new_reasons,
            plan_id=row.plan_id, revision=row.revision, plan_status=row.status,
            is_active=active is not None and active.id == row.id, inventory_version=exported.inventory_version)

    def scarcity(self, request):
        from .scarcity import analyze_scarcity

        baseline = self.find_candidates(request)
        snapshot = self.load_snapshot(request.dataset_id)
        base = self._plan_row(request.dataset_id, request.base_plan_id) if request.base_plan_id else self._active_plan_row(request.dataset_id)
        assignments = self._assignments(base) if base else []
        pending = [a.part_id for a in assignments if a.remnant_id == NEW] if base else list(snapshot.parts)
        occupied = {a.remnant_id for a in assignments if a.remnant_id != NEW}
        return analyze_scarcity(snapshot, request, baseline, pending, occupied,
            inventory_version=baseline.inventory_version, plan_id=base.plan_id if base else None,
            plan_revision=base.revision if base else None)

    def geometry_margins(self, dataset_id: str, plan_id: str, revision: int | None = None):
        from .insights import geometry_margins

        exported = self.export(dataset_id, plan_id, revision)
        row = self._plan_row(dataset_id, plan_id, revision)
        return geometry_margins(self.load_snapshot(dataset_id), self._assignments(row), plan_id=row.plan_id,
            revision=row.revision, inventory_version=exported.inventory_version)

    def find_candidates(self, request: FindRequest) -> Candidates:
        """Fast single-part (or joint quantity) placement without rebuilding the plan. Read-only."""
        snapshot = self.load_snapshot(request.dataset_id)
        token = self.inventory_token(request.dataset_id)
        if request.material_id not in snapshot.materials:
            return Candidates(candidates=[], reason_codes=["UNKNOWN_MATERIAL"], scope=request.inventory_mode,
                              requested_quantity=request.quantity, reasons_ru=[REASON_RU["UNKNOWN_MATERIAL"]],
                              inventory_version=token)
        part = PartSpec("__request__", "__request__", request.material_id, request.dimensions.length_mm,
                        request.dimensions.width_mm, request.premium)
        active = self._active_plan_row(request.dataset_id)
        base = self._plan_row(request.dataset_id, request.base_plan_id) if request.base_plan_id else active
        plan_assignments = self._assignments(base) if base else []
        occupied_by_plan: dict[str, list[Assignment]] = defaultdict(list)
        for a in plan_assignments:
            if a.remnant_id != NEW:
                occupied_by_plan[a.remnant_id].append(a)
        tempered = snapshot.is_tempered(request.material_id)
        reasons: dict[str, int] = defaultdict(int)
        options: list[tuple] = []  # (sort key, remnant, capacity positions, shares)
        for rid in snapshot.remnant_order:
            r = snapshot.remnants[rid]
            reason = pair_reason(snapshot, part, r)
            if reason is not None:
                reasons[reason] += 1
                continue
            if r.status in {"consumed", "withdrawn"}:
                reasons["REMNANT_UNAVAILABLE"] += 1
                continue
            occupied = rid in occupied_by_plan or r.status == "reserved"
            if occupied and (request.inventory_mode == "free_whole_remnants" or r.status == "reserved" or tempered):
                reasons["OCCUPIED"] += 1
                continue
            positions = self._positions(snapshot, part, r, occupied_by_plan.get(rid, []), request.quantity, tempered)
            if not positions:
                reasons["SIZE_TOO_LARGE" if not occupied else "OCCUPIED"] += 1
                continue
            waste = r.area - part.area * len(positions)
            options.append(((bool(occupied), waste, -(r.age_days or 0), rid), r, positions, occupied))
        options.sort(key=lambda o: o[0])
        candidates: list[Candidate] = []
        remaining = request.quantity
        for _, r, positions, shares in options:
            if remaining <= 0:
                break
            for x, y, rot in positions[:remaining]:
                candidates.append(Candidate(
                    remnant_id=r.remnant_id, remnant_version=r.version, x_mm=x, y_mm=y, rot=rot,
                    location_raw=r.location_raw, copy_index=request.quantity - remaining,
                    remnant_dimensions=Dimensions(length_mm=r.length_mm, width_mm=r.width_mm),
                    waste_area_mm2=max(0, r.area - part.area), age_days=r.age_days, shares_remnant_with_plan=shares))
                remaining -= 1
            if request.quantity == 1:
                break
        if request.quantity == 1 and options:
            # Offer alternatives for the manager, each one a complete independent option.
            for _, r, positions, shares in options[1:5]:
                x, y, rot = positions[0]
                candidates.append(Candidate(
                    remnant_id=r.remnant_id, remnant_version=r.version, x_mm=x, y_mm=y, rot=rot,
                    location_raw=r.location_raw, copy_index=0,
                    remnant_dimensions=Dimensions(length_mm=r.length_mm, width_mm=r.width_mm),
                    waste_area_mm2=max(0, r.area - part.area), age_days=r.age_days, shares_remnant_with_plan=shares))
        covered = request.quantity - max(0, remaining)
        codes = []
        if covered < request.quantity:
            if covered > 0:
                codes.append("INSUFFICIENT_JOINT_CAPACITY")
            for code in ("OCCUPIED", "REMNANT_UNAVAILABLE", "PREMIUM_ON_DEFECT", "TEMPERED_SIZE_MISMATCH",
                         "SIZE_TOO_LARGE", "MATERIAL_MISMATCH"):
                if reasons.get(code):
                    codes.append(code)
            if not reasons:
                codes.append("MATERIAL_MISMATCH")
            if request.inventory_mode == "free_whole_remnants":
                codes.append("LIMITED_SEARCH")
        reasons_ru = [REASON_RU.get(c, "Совместного места недостаточно для всего количества") for c in codes]
        scope = request.inventory_mode + (f":{base.plan_id}@{base.revision}" if base else "")
        return Candidates(candidates=candidates, reason_codes=codes, scope=scope, covered_quantity=covered,
                          requested_quantity=request.quantity, reasons_ru=reasons_ru, inventory_version=token)

    def alternatives(self, request: FindRequest, excluding: str) -> list[str]:
        """Complete alternatives for one whole-piece order; excludes the owning piece."""
        snapshot = self.load_snapshot(request.dataset_id)
        if request.material_id not in snapshot.materials:
            return []
        part = PartSpec("__request__", "__request__", request.material_id,
                        request.dimensions.length_mm, request.dimensions.width_mm, request.premium)
        active = self._active_plan_row(request.dataset_id)
        occupied = {a.remnant_id for a in self._assignments(active)} if active else set()
        result = []
        for rid, piece in snapshot.remnants.items():
            if rid == excluding or rid in occupied or piece.status != "available" or pair_reason(snapshot, part, piece):
                continue
            positions = self._positions(snapshot, part, piece, [], request.quantity, snapshot.is_tempered(part.material_id))
            if len(positions) == request.quantity:
                result.append((piece.area - part.area * request.quantity, -(piece.age_days or 0), rid))
        return [rid for _, _, rid in sorted(result)[:5]]

    @staticmethod
    def _positions(snapshot: Snapshot, part: PartSpec, r: RemnantSpec, existing: list[Assignment],
                   quantity: int, tempered: bool) -> list[tuple[int, int, int]]:
        if tempered:
            from .domain import tempered_orientation

            rot = tempered_orientation(part, r)
            return [(0, 0, rot)] if rot is not None and not existing else []
        bin_ = MaxRectsBin(r.length_mm, r.width_mm, "bl")
        for a in existing:
            p = snapshot.parts.get(a.part_id)
            if p is None or a.x_mm is None or a.y_mm is None or a.rot is None:
                continue
            w, h = oriented_size(p, a.rot)
            bin_.insert_at(-1, a.x_mm, a.y_mm, w + GAP_MM, h + GAP_MM, a.rot)
        positions = []
        for k in range(quantity):  # joint capacity: copies are packed together, never one promise repeated
            if not bin_.insert(Item(k, part.length_mm, part.width_mm)):
                break
            _, x, y, rot = bin_.placed[-1]
            positions.append((x, y, rot))
        return positions
