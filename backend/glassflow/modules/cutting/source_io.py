"""Strict reading of the organisers' cutting CSV format into a solver snapshot, and solution.csv rows.

Used by tests, the evidence CLI and (via ``rows_to_snapshot``) by the platform importer, which owns
file upload, hashing and the dataset registry. Nothing here reads KEY files or research solutions.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .domain import NEW, Assignment, MaterialSpec, PartSpec, RemnantSpec, Snapshot

MATERIAL_HEADER = ["material_id", "название", "толщина_мм", "цена_нового_стекла_тг_за_м2", "закалённое"]
STOCK_HEADER = ["remnant_id", "material_id", "длина_мм", "ширина_мм", "возраст_дней", "дефект", "место"]
ORDER_HEADER = ["order_id", "part_id", "material_id", "длина_мм", "ширина_мм", "премиум", "тип_изделия"]
SOLUTION_HEADER = ["part_id", "remnant_id", "x_mm", "y_mm", "rot"]

_POSITIVE = re.compile(r"^[1-9]\d*$")
_NONNEG = re.compile(r"^\d+$")


@dataclass(frozen=True, slots=True)
class RowError:
    file: str
    row: int
    field: str
    value: str
    code: str
    message_ru: str


class SourceError(ValueError):
    def __init__(self, errors: list[RowError]):
        super().__init__("; ".join(f"{e.file}:{e.row}:{e.field}:{e.code}" for e in errors[:20]))
        self.errors = errors


def read_csv_text(data: bytes) -> list[dict[str, str]]:
    text = data.decode("utf-8-sig")  # BOM is recognised and normalised; original bytes stay with the platform
    return list(csv.DictReader(io.StringIO(text, newline="")))


def _check_header(name: str, rows: list[dict[str, str]], header: list[str], errors: list[RowError]) -> bool:
    got = list(rows[0].keys()) if rows else []
    if rows and got != header:
        errors.append(RowError(name, 1, "header", ",".join(got), "BAD_HEADER", f"Ожидались колонки {header}"))
        return False
    return True


def _int(name, row_no, row, field, errors, positive=True, allow_empty=False) -> int | None:
    value = (row.get(field) or "").strip()
    if value == "" and allow_empty:
        return None
    pattern = _POSITIVE if positive else _NONNEG
    if not pattern.match(value):
        code = "NEGATIVE_OR_ZERO" if value.lstrip("-").isdigit() else "NOT_INTEGER"
        errors.append(RowError(name, row_no, field, value, code, "Ожидалось целое положительное число мм"
                               if positive else "Ожидалось целое неотрицательное число"))
        return None
    return int(value)


def _flag(name, row_no, row, field, errors) -> bool | None:
    value = (row.get(field) or "").strip()
    if value not in {"0", "1"}:
        errors.append(RowError(name, row_no, field, value, "NOT_BINARY", "Допустимы только 0 или 1"))
        return None
    return value == "1"


def rows_to_snapshot(
    dataset_id: str,
    materials: list[Mapping[str, str]],
    stock: list[Mapping[str, str]],
    orders: list[Mapping[str, str]],
) -> tuple[Snapshot, list[RowError]]:
    """Build a snapshot; rows with errors are reported and excluded from cutting, never silently fixed."""
    errors: list[RowError] = []
    materials = [dict(r) for r in materials]
    stock = [dict(r) for r in stock]
    orders = [dict(r) for r in orders]
    _check_header("materials.csv", materials, MATERIAL_HEADER, errors)
    _check_header("stock.csv", stock, STOCK_HEADER, errors)
    _check_header("orders.csv", orders, ORDER_HEADER, errors)
    mats: dict[str, MaterialSpec] = {}
    for i, row in enumerate(materials, start=2):
        mid = (row.get("material_id") or "").strip()
        tempered = _flag("materials.csv", i, row, "закалённое", errors)
        thickness = _int("materials.csv", i, row, "толщина_мм", errors)
        raw_price = (row.get("цена_нового_стекла_тг_за_м2") or "").strip()
        try:
            price = Decimal(raw_price)
            if price < 0 or not price.is_finite():
                raise InvalidOperation
        except InvalidOperation:
            errors.append(RowError("materials.csv", i, "цена_нового_стекла_тг_за_м2", raw_price, "BAD_MONEY",
                                   "Ставка должна быть неотрицательным десятичным числом"))
            continue
        if not mid:
            errors.append(RowError("materials.csv", i, "material_id", "", "EMPTY", "Пустой material_id"))
            continue
        if mid in mats:
            errors.append(RowError("materials.csv", i, "material_id", mid, "DUPLICATE_ID", "Повтор material_id"))
            continue
        if tempered is None or thickness is None:
            continue
        mats[mid] = MaterialSpec(mid, tempered, price, (row.get("название") or "").strip(), thickness)
    remnants: dict[str, RemnantSpec] = {}
    for i, row in enumerate(stock, start=2):
        rid = (row.get("remnant_id") or "").strip()
        mid = (row.get("material_id") or "").strip()
        length = _int("stock.csv", i, row, "длина_мм", errors)
        width = _int("stock.csv", i, row, "ширина_мм", errors)
        age = _int("stock.csv", i, row, "возраст_дней", errors, positive=False, allow_empty=True)
        defect = _flag("stock.csv", i, row, "дефект", errors)
        if not rid or rid.upper() == NEW:
            errors.append(RowError("stock.csv", i, "remnant_id", rid, "BAD_ID", "Пустой или зарезервированный ID"))
            continue
        if rid in remnants:
            errors.append(RowError("stock.csv", i, "remnant_id", rid, "DUPLICATE_ID", "Повтор remnant_id"))
            continue
        if mid not in mats:
            errors.append(RowError("stock.csv", i, "material_id", mid, "UNKNOWN_MATERIAL",
                                   "Неизвестный material_id блокирует использование строки в раскрое"))
            continue
        if None in (length, width, defect):
            continue
        remnants[rid] = RemnantSpec(rid, mid, length, width, bool(defect), age, "available", 0,
                                    (row.get("место") or "").strip(), True)
    parts: dict[str, PartSpec] = {}
    for i, row in enumerate(orders, start=2):
        pid = (row.get("part_id") or "").strip()
        oid = (row.get("order_id") or "").strip()
        mid = (row.get("material_id") or "").strip()
        length = _int("orders.csv", i, row, "длина_мм", errors)
        width = _int("orders.csv", i, row, "ширина_мм", errors)
        premium = _flag("orders.csv", i, row, "премиум", errors)
        if not pid or not oid:
            errors.append(RowError("orders.csv", i, "part_id", pid, "EMPTY", "Пустой part_id/order_id"))
            continue
        if pid in parts:
            errors.append(RowError("orders.csv", i, "part_id", pid, "DUPLICATE_ID", "Повтор part_id"))
            continue
        if mid not in mats:
            # The part stays in the plan (it must appear in solution.csv as NEW) but cannot use stock.
            errors.append(RowError("orders.csv", i, "material_id", mid, "UNKNOWN_MATERIAL",
                                   "Неизвестный material_id: деталь не может быть покрыта остатком"))
        if None in (length, width, premium):
            continue
        parts[pid] = PartSpec(pid, oid, mid, length, width, bool(premium), (row.get("тип_изделия") or "").strip())
    return Snapshot(dataset_id, mats, remnants, parts), errors


def load_pack(directory: Path, stock: str = "stock_open.csv", orders: str = "orders_open.csv",
              materials: str = "materials.csv", dataset_id: str = "open-pack") -> Snapshot:
    snapshot, errors = rows_to_snapshot(
        dataset_id,
        read_csv_text((directory / materials).read_bytes()),
        read_csv_text((directory / stock).read_bytes()),
        read_csv_text((directory / orders).read_bytes()),
    )
    blocking = [e for e in errors if e.code != "UNKNOWN_MATERIAL" or e.file != "orders.csv"]
    if blocking:
        raise SourceError(blocking)
    return snapshot


def solution_rows(snapshot: Snapshot, assignments: Mapping[str, Assignment]) -> list[dict[str, str]]:
    """Exact contest rows in input part order; tempered placements are exported as x=0,y=0,rot."""
    rows = []
    for pid in snapshot.part_order:
        a = assignments.get(pid)
        if a is None or a.remnant_id == NEW:
            rows.append({"part_id": pid, "remnant_id": NEW, "x_mm": "", "y_mm": "", "rot": ""})
        else:
            rows.append({"part_id": pid, "remnant_id": a.remnant_id, "x_mm": str(a.x_mm), "y_mm": str(a.y_mm),
                         "rot": str(a.rot)})
    return rows


def write_solution_csv(path: Path, rows: Iterable[Mapping[str, str]]) -> None:
    """UTF-8 without BOM, comma, standard quoting; temp file then atomic replace."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOLUTION_HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)
