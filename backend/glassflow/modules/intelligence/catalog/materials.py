"""Read-only view of materials.csv for catalog mapping.

Warehouse materials belong to the inventory domain (Claude 2). This module only needs the
identifier, name, thickness and tempered flag to propose explicit mappings and to keep the
material valuation rate visibly separate from client catalog prices.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

EXPECTED_HEADER = ["material_id", "название", "толщина_мм", "цена_нового_стекла_тг_за_м2", "закалённое"]


class MaterialsError(ValueError):
    pass


@dataclass(frozen=True)
class MaterialRecord:
    material_id: str
    name: str
    thickness_mm: int
    valuation_rate_per_m2: Decimal
    tempered: bool


@dataclass(frozen=True)
class MaterialsTable:
    version: str
    sha256: str
    records: tuple[MaterialRecord, ...]

    def get(self, material_id: str) -> MaterialRecord | None:
        for record in self.records:
            if record.material_id == material_id:
                return record
        return None


def parse_materials(content: bytes) -> MaterialsTable:
    digest = hashlib.sha256(content).hexdigest()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MaterialsError("materials.csv должен быть в UTF-8") from exc
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if header != EXPECTED_HEADER:
        raise MaterialsError(f"materials.csv: неожиданные заголовки {header}")
    records: list[MaterialRecord] = []
    seen: set[str] = set()
    for line_no, row in enumerate(reader, start=2):
        if not row or all(not cell.strip() for cell in row):
            continue
        if len(row) != len(EXPECTED_HEADER):
            raise MaterialsError(f"materials.csv строка {line_no}: ожидается {len(EXPECTED_HEADER)} полей")
        material_id, name, thickness, rate, tempered = row
        if material_id in seen:
            raise MaterialsError(f"materials.csv строка {line_no}: повтор material_id {material_id}")
        seen.add(material_id)
        try:
            thickness_mm = int(thickness)
            valuation = Decimal(rate)
        except (ValueError, InvalidOperation) as exc:
            raise MaterialsError(f"materials.csv строка {line_no}: нечисловое значение") from exc
        if tempered not in {"0", "1"}:
            raise MaterialsError(f"materials.csv строка {line_no}: закалённое должно быть 0/1")
        records.append(MaterialRecord(material_id, name, thickness_mm, valuation, tempered == "1"))
    return MaterialsTable(f"materials-{digest[:16]}", digest, tuple(records))
