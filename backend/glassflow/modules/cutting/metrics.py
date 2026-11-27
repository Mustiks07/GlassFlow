"""Plan metrics derived only from independently validated placements.

Coverage denominator = area of ALL input parts of the dataset (demo parts in a working copy count only
in that working copy). Material valuation = sum(part area m² × materials.csv rate): a valuation at the
price list, not profit. Money uses Decimal; integer mm² for areas.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from glassflow.contracts.cutting import CutMetrics, MaterialValue

from .domain import Snapshot
from .geometry import ValidationReport
from .solver import score

CENT = Decimal("0.01")
MM2_PER_M2 = Decimal(1_000_000)


def money(value: Decimal) -> str:
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def exact_value(snapshot: Snapshot, covered: dict[str, str]) -> tuple[Decimal, dict[str, tuple[int, Decimal]]]:
    by_material: dict[str, int] = defaultdict(int)
    for pid in covered:
        part = snapshot.parts[pid]
        by_material[part.material_id] += part.area
    total = Decimal(0)
    detail = {}
    for mid, area in sorted(by_material.items()):
        value = Decimal(area) * snapshot.materials[mid].price_per_m2 / MM2_PER_M2
        total += value
        detail[mid] = (area, value)
    return total, detail


def compute_metrics(snapshot: Snapshot, report: ValidationReport, new_reasons: dict[str, str] | None = None
                    ) -> tuple[CutMetrics, list[str]]:
    covered = report.ok_part_ids if report.valid else {
        pid: rid for pid, rid in report.ok_part_ids.items() if pid not in set(report.invalid_part_ids)
    }
    total_area = snapshot.total_part_area
    covered_area = sum(snapshot.parts[pid].area for pid in covered)
    value, detail = exact_value(snapshot, covered)
    orders: dict[str, list[str]] = defaultdict(list)
    for pid in snapshot.part_order:
        orders[snapshot.parts[pid].order_id].append(pid)
    full = sum(1 for parts in orders.values() if all(p in covered for p in parts))
    used = set(covered.values())
    originals = [rid for rid in snapshot.remnant_order if snapshot.remnants[rid].original]
    # A reserved/consumed/withdrawn piece is not free even if this plan does not use it.
    free_original = [rid for rid in originals if rid not in used and snapshot.remnants[rid].status == "available"]
    coverage = covered_area / total_area if total_area else 0.0
    invalid = len(set(report.invalid_part_ids)) + sum(1 for i in report.issues if i.part_id is None)
    percent = (Decimal(covered_area) * 100 / Decimal(total_area)) if total_area else Decimal(0)
    metrics = CutMetrics(
        covered_area_mm2=covered_area,
        total_area_mm2=total_area,
        coverage=coverage,
        replacement_value_tg=money(value),
        invalid=invalid,
        missing=len(report.missing_part_ids),
        fully_covered_orders=full,
        total_orders=len(orders),
        covered_parts=len(covered),
        total_parts=len(snapshot.part_order),
        used_original_remnants=sum(1 for rid in used if snapshot.remnants[rid].original),
        free_original_remnants=len(free_original),
        used_remnants=len(used),
        score=round(score(coverage, invalid), 6),
        coverage_percent=str(percent.quantize(Decimal("0.0000001"), rounding=ROUND_HALF_UP)),
        value_by_material=[
            MaterialValue(
                material_id=mid,
                covered_area_mm2=area,
                unit_price_tg=str(snapshot.materials[mid].price_per_m2),
                value_tg=money(v),
            )
            for mid, (area, v) in detail.items()
        ],
        new_reasons=dict(new_reasons or {}),
    )
    return metrics, free_original
