"""Independent strict geometry validator.

This module never calls the solver and never trusts how a plan was produced. It is at least as
strict as the organisers' ``validate.py`` and additionally checks completeness, uniqueness,
types, dataset scope, availability and locks. Every issue has a stable ``code``, the object it
refers to, a Russian explanation and the relevant coordinates.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from .domain import (
    GAP_MM,
    NEW,
    TRIM_MM,
    Assignment,
    PartSpec,
    RemnantSpec,
    Snapshot,
    oriented_size,
    tempered_orientation,
)

PLAN_LEVEL = "__plan__"


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    message_ru: str
    part_id: str | None = None
    remnant_id: str | None = None
    other_part_id: str | None = None
    coordinates: dict[str, int] = field(default_factory=dict)

    def as_text(self) -> str:
        subject = self.part_id or self.remnant_id or PLAN_LEVEL
        return f"{self.code}:{subject}: {self.message_ru}"


@dataclass(slots=True)
class ValidationReport:
    issues: list[Issue]
    ok_part_ids: dict[str, str]
    """part_id -> remnant_id for placements on stock that passed every check."""
    invalid_part_ids: list[str]
    missing_part_ids: list[str]
    new_part_ids: list[str]

    @property
    def valid(self) -> bool:
        return not self.issues


@dataclass(frozen=True, slots=True)
class _Rect:
    part_id: str
    x: int
    y: int
    w: int
    h: int


def separated(a: _Rect | tuple[int, int, int, int], b: _Rect | tuple[int, int, int, int]) -> bool:
    """True when at least one axis separates the rectangles by >= GAP_MM (touching at 3 mm is ok)."""
    ax, ay, aw, ah = (a.x, a.y, a.w, a.h) if isinstance(a, _Rect) else a
    bx, by, bw, bh = (b.x, b.y, b.w, b.h) if isinstance(b, _Rect) else b
    return (
        ax + aw + GAP_MM <= bx
        or bx + bw + GAP_MM <= ax
        or ay + ah + GAP_MM <= by
        or by + bh + GAP_MM <= ay
    )


def _overlap(a: _Rect, b: _Rect) -> bool:
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


def validate_plan(
    snapshot: Snapshot,
    assignments: Iterable[Assignment],
    *,
    unavailable_remnant_ids: Iterable[str] = (),
    locks: Iterable[Assignment] = (),
    require_complete: bool = True,
) -> ValidationReport:
    """Validate a complete plan. ``unavailable_remnant_ids`` excludes reserved/consumed stock."""
    issues: list[Issue] = []
    bad: set[str] = set()
    seen: set[str] = set()
    by_remnant: dict[str, list[tuple[Assignment, PartSpec]]] = defaultdict(list)
    unavailable = set(unavailable_remnant_ids)
    new_ids: list[str] = []
    rows = list(assignments)
    by_part: dict[str, Assignment] = {}

    def fail(code: str, message: str, part_id: str | None, remnant_id: str | None = None, **kw) -> None:
        issues.append(Issue(code, message, part_id, remnant_id, **kw))
        if part_id is not None:
            bad.add(part_id)

    for row in rows:
        pid = row.part_id
        if pid in seen:
            fail("DUPLICATE_PART", f"Деталь {pid} указана в плане больше одного раза.", pid, row.remnant_id)
            continue
        seen.add(pid)
        part = snapshot.parts.get(pid)
        if part is None:
            fail("UNKNOWN_PART", f"Детали {pid} нет в заказах этого набора данных.", pid, row.remnant_id)
            continue
        by_part[pid] = row
        if row.remnant_id == NEW:
            if row.x_mm is not None or row.y_mm is not None or row.rot is not None:
                fail("NEW_WITH_COORDINATES", f"Деталь {pid} отмечена NEW, координаты должны быть пустыми.", pid)
            else:
                new_ids.append(pid)
            continue
        remnant = snapshot.remnants.get(row.remnant_id)
        if remnant is None:
            fail(
                "UNKNOWN_REMNANT",
                f"Остатка {row.remnant_id} нет на складе этого набора данных.",
                pid,
                row.remnant_id,
            )
            continue
        if row.remnant_id in unavailable or remnant.status in {"consumed", "withdrawn"}:
            fail(
                "REMNANT_UNAVAILABLE",
                f"Остаток {row.remnant_id} недоступен (статус {remnant.status} или занят другим планом).",
                pid,
                row.remnant_id,
            )
            continue
        material = snapshot.materials.get(remnant.material_id)
        if material is None or part.material_id not in snapshot.materials:
            fail("UNKNOWN_MATERIAL", "Материал детали или остатка отсутствует в materials.", pid, row.remnant_id)
            continue
        if part.material_id != remnant.material_id:
            fail(
                "MATERIAL_MISMATCH",
                f"Материал детали {part.material_id} не совпадает с материалом остатка {remnant.material_id}.",
                pid,
                row.remnant_id,
            )
            continue
        if part.premium and remnant.defect:
            fail(
                "PREMIUM_ON_DEFECT",
                "Премиум-деталь нельзя резать из остатка с дефектом (геометрия дефекта неизвестна).",
                pid,
                row.remnant_id,
            )
            continue
        if material.tempered:
            orientation = tempered_orientation(part, remnant)
            if orientation is None:
                fail(
                    "TEMPERED_SIZE_MISMATCH",
                    f"Калёное стекло резать нельзя: {part.length_mm}×{part.width_mm} не совпадает с "
                    f"{remnant.length_mm}×{remnant.width_mm} в пределах ±2 мм.",
                    pid,
                    row.remnant_id,
                )
                continue
            coords = (row.x_mm, row.y_mm, row.rot)
            if coords != (None, None, None):
                if row.x_mm != 0 or row.y_mm != 0 or row.rot is None or tempered_orientation_ok(
                    part, remnant, row.rot
                ) is False:
                    fail(
                        "TEMPERED_BAD_COORDINATES",
                        "Для калёного куска координаты пустые либо x=0, y=0 и rot совпадающей ориентации.",
                        pid,
                        row.remnant_id,
                        coordinates={"x_mm": row.x_mm or 0, "y_mm": row.y_mm or 0, "rot": row.rot or 0},
                    )
                    continue
            by_remnant[row.remnant_id].append((row, part))
            continue
        if row.x_mm is None or row.y_mm is None or row.rot is None:
            fail("MISSING_COORDINATES", f"Для детали {pid} нет x_mm, y_mm или rot.", pid, row.remnant_id)
            continue
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (row.x_mm, row.y_mm, row.rot)):
            fail("NON_INTEGER_VALUE", "Координаты и rot должны быть целыми числами.", pid, row.remnant_id)
            continue
        if row.rot not in (0, 1):
            fail("INVALID_ROTATION", "rot допускает только 0 или 1.", pid, row.remnant_id)
            continue
        if row.x_mm < 0 or row.y_mm < 0:
            fail("NEGATIVE_VALUE", "Координаты не могут быть отрицательными.", pid, row.remnant_id)
            continue
        w, h = oriented_size(part, row.rot)
        x, y = row.x_mm, row.y_mm
        if x < TRIM_MM or y < TRIM_MM or x + w > remnant.length_mm - TRIM_MM or y + h > remnant.width_mm - TRIM_MM:
            fail(
                "OUT_OF_BOUNDS",
                f"Деталь выходит за рабочую область остатка с отступом {TRIM_MM} мм: "
                f"x={x}, y={y}, w={w}, h={h}, остаток {remnant.length_mm}×{remnant.width_mm}.",
                pid,
                row.remnant_id,
                coordinates={"x_mm": x, "y_mm": y, "w_mm": w, "h_mm": h},
            )
            continue
        by_remnant[row.remnant_id].append((row, part))

    for remnant_id, items in by_remnant.items():
        remnant = snapshot.remnants[remnant_id]
        if snapshot.is_tempered(remnant.material_id):
            if len(items) > 1:
                for row, _ in items:
                    fail(
                        "TEMPERED_MULTIPLE_PARTS",
                        f"В калёный остаток {remnant_id} можно поставить только одну целую деталь.",
                        row.part_id,
                        remnant_id,
                    )
            continue
        rects = []
        for row, part in items:
            w, h = oriented_size(part, row.rot or 0)
            rects.append(_Rect(row.part_id, row.x_mm or 0, row.y_mm or 0, w, h))
        rects.sort(key=lambda r: (r.x, r.y, r.part_id))
        for i, a in enumerate(rects):
            for b in rects[i + 1 :]:
                if b.x >= a.x + a.w + GAP_MM:
                    break  # sorted by x: no further rectangle can conflict with ``a``
                if not separated(a, b):
                    code = "OVERLAP" if _overlap(a, b) else "GAP_VIOLATION"
                    message = (
                        f"Детали {a.part_id} и {b.part_id} пересекаются."
                        if code == "OVERLAP"
                        else f"Между {a.part_id} и {b.part_id} нет зазора {GAP_MM} мм ни по одной оси."
                    )
                    coordinates = {"ax": a.x, "ay": a.y, "aw": a.w, "ah": a.h, "bx": b.x, "by": b.y, "bw": b.w, "bh": b.h}
                    fail(code, message, a.part_id, remnant_id, other_part_id=b.part_id, coordinates=coordinates)
                    fail(code, message, b.part_id, remnant_id, other_part_id=a.part_id, coordinates=coordinates)

    for lock in locks:
        row = by_part.get(lock.part_id)
        if lock.lock_kind == "none":
            continue
        if row is None or row.remnant_id != lock.remnant_id:
            fail(
                "LOCK_VIOLATED",
                f"Закрепление детали {lock.part_id} на остатке {lock.remnant_id} нарушено.",
                lock.part_id,
                lock.remnant_id,
            )
        elif lock.lock_kind == "placement" and (row.x_mm, row.y_mm, row.rot) != (lock.x_mm, lock.y_mm, lock.rot):
            fail(
                "LOCK_VIOLATED",
                f"Закрепленное размещение детали {lock.part_id} изменено.",
                lock.part_id,
                lock.remnant_id,
                coordinates={"x_mm": lock.x_mm or 0, "y_mm": lock.y_mm or 0, "rot": lock.rot or 0},
            )

    missing = [pid for pid in snapshot.part_order if pid not in seen]
    if require_complete:
        for pid in missing:
            issues.append(Issue("MISSING_PART", f"Деталь {pid} отсутствует в плане (нужна строка либо NEW).", pid))
    ok = {
        pid: row.remnant_id
        for pid, row in by_part.items()
        if pid not in bad and row.remnant_id != NEW
    }
    invalid = sorted(bad)
    return ValidationReport(issues, ok, invalid, missing, new_ids)


def tempered_orientation_ok(part: PartSpec, remnant: RemnantSpec, rot: int) -> bool:
    """rot=0 means the part length lies along the remnant length (same convention as ordinary)."""
    from .domain import TEMPERED_TOLERANCE_MM as tol

    w, h = oriented_size(part, rot)
    return abs(w - remnant.length_mm) <= tol and abs(h - remnant.width_mm) <= tol


def canonical_tempered(part: PartSpec, remnant: RemnantSpec) -> Assignment | None:
    rot = tempered_orientation(part, remnant)
    if rot is None:
        return None
    return Assignment(part.part_id, remnant.remnant_id, 0, 0, rot)


_INT = re.compile(r"^\d+$")


def parse_solution_rows(rows: Iterable[Mapping[str, str]]) -> tuple[list[Assignment], list[Issue]]:
    """Strictly parse solution.csv rows. Rejects ``int(float(...))`` style values the official script tolerates."""
    parsed: list[Assignment] = []
    issues: list[Issue] = []
    for index, row in enumerate(rows, start=2):
        pid = (row.get("part_id") or "").strip()
        rid = (row.get("remnant_id") or "").strip()
        if not pid:
            issues.append(Issue("EMPTY_FIELD", f"Строка {index}: пустой part_id."))
            continue
        if not rid:
            issues.append(Issue("EMPTY_FIELD", f"Строка {index}: пустой remnant_id (используйте NEW).", pid))
            continue
        raw = [(row.get(k) or "").strip() for k in ("x_mm", "y_mm", "rot")]
        if rid == NEW and all(v == "" for v in raw):
            parsed.append(Assignment(pid, NEW))
            continue
        values: list[int | None] = []
        broken = False
        for name, value in zip(("x_mm", "y_mm", "rot"), raw, strict=True):
            if value == "":
                values.append(None)
            elif value.startswith("-") and _INT.match(value[1:]):
                issues.append(Issue("NEGATIVE_VALUE", f"Строка {index}: {name}={value} отрицательно.", pid, rid))
                broken = True
            elif not _INT.match(value):
                issues.append(Issue("NON_INTEGER_VALUE", f"Строка {index}: {name}={value!r} не целое.", pid, rid))
                broken = True
            else:
                values.append(int(value))
        if broken:
            continue
        x, y, rot = values
        if rot is not None and rot not in (0, 1):
            issues.append(Issue("INVALID_ROTATION", f"Строка {index}: rot={rot}, допустимы 0/1.", pid, rid))
            continue
        parsed.append(Assignment(pid, rid, x, y, rot))
    return parsed, issues
