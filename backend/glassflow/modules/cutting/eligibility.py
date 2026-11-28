"""Eligibility graph part -> remnant with explicit rejection reasons.

Reason codes are stable API values (see docs/status/CLAUDE_2_MYRZABEK.md):
MATERIAL_MISMATCH, UNKNOWN_MATERIAL, PREMIUM_ON_DEFECT, SIZE_TOO_LARGE, TEMPERED_SIZE_MISMATCH,
REMNANT_UNAVAILABLE, OCCUPIED, LOCK_CONFLICT, LIMITED_SEARCH, NO_COMPATIBLE_REMNANT.
``catalog unmapped`` is intentionally NOT a cutting reason: it belongs to the catalog module.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .domain import PartSpec, RemnantSpec, Snapshot, ordinary_fits, tempered_orientation

REASON_RU = {
    "MATERIAL_MISMATCH": "Нет остатка того же материала",
    "UNKNOWN_MATERIAL": "Материал отсутствует в materials",
    "PREMIUM_ON_DEFECT": "Премиум-деталь нельзя резать из остатка с дефектом",
    "SIZE_TOO_LARGE": "Деталь не помещается в рабочую область остатка с отступом 5 мм",
    "TEMPERED_SIZE_MISMATCH": "Калёное стекло: размеры не совпадают с целым куском в пределах ±2 мм",
    "REMNANT_UNAVAILABLE": "Подходящие остатки списаны, исключены или зарезервированы",
    "OCCUPIED": "Подходящие куски заняты действующими заданиями (режим без перестройки)",
    "LOCK_CONFLICT": "Конфликт закреплений",
    "LIMITED_SEARCH": "Поиск не нашел размещение за лимит; это не доказательство невозможности",
    "NO_COMPATIBLE_REMNANT": "Нет совместимого остатка",
    "NOT_PLACED_BY_EDIT": "Деталь оставлена NEW в сохраненном плане; это не доказательство невозможности раскроя",
}


def pair_reason(snapshot: Snapshot, part: PartSpec, remnant: RemnantSpec) -> str | None:
    """None when the part can be placed alone on the remnant; otherwise the first failing reason."""
    if part.material_id not in snapshot.materials or remnant.material_id not in snapshot.materials:
        return "UNKNOWN_MATERIAL"
    if part.material_id != remnant.material_id:
        return "MATERIAL_MISMATCH"
    if part.premium and remnant.defect:
        return "PREMIUM_ON_DEFECT"
    if snapshot.is_tempered(part.material_id):
        return None if tempered_orientation(part, remnant) is not None else "TEMPERED_SIZE_MISMATCH"
    return None if ordinary_fits(part, remnant) else "SIZE_TOO_LARGE"


@dataclass(slots=True)
class Eligibility:
    eligible: dict[str, list[str]]
    reasons: dict[str, str] = field(default_factory=dict)
    """part_id -> dominant reason when the part has no eligible remnant at all."""


def build_eligibility(
    snapshot: Snapshot, available: set[str] | None = None, occupied: set[str] | None = None
) -> Eligibility:
    available = set(snapshot.remnant_order) if available is None else available
    occupied = occupied or set()
    by_material: dict[str, list[RemnantSpec]] = {}
    for rid in snapshot.remnant_order:
        remnant = snapshot.remnants[rid]
        by_material.setdefault(remnant.material_id, []).append(remnant)
    eligible: dict[str, list[str]] = {}
    reasons: dict[str, str] = {}
    for pid in snapshot.part_order:
        part = snapshot.parts[pid]
        result: list[str] = []
        counts: Counter[str] = Counter()
        if part.material_id not in snapshot.materials:
            eligible[pid] = []
            reasons[pid] = "UNKNOWN_MATERIAL"
            continue
        same = by_material.get(part.material_id, [])
        if not same:
            reasons[pid] = "MATERIAL_MISMATCH"
        for remnant in same:
            reason = pair_reason(snapshot, part, remnant)
            if reason is None and remnant.remnant_id in occupied:
                reason = "OCCUPIED"
            elif reason is None and (remnant.remnant_id not in available or remnant.status != "available"):
                reason = "REMNANT_UNAVAILABLE"
            if reason is None:
                result.append(remnant.remnant_id)
            else:
                counts[reason] += 1
        eligible[pid] = result
        if not result and pid not in reasons:
            # Prefer the most actionable explanation: availability before physical size.
            for code in ("OCCUPIED", "REMNANT_UNAVAILABLE", "PREMIUM_ON_DEFECT", "TEMPERED_SIZE_MISMATCH",
                         "SIZE_TOO_LARGE"):
                if counts[code]:
                    reasons[pid] = code
                    break
            else:
                reasons[pid] = "NO_COMPATIBLE_REMNANT"
    return Eligibility(eligible, reasons)
