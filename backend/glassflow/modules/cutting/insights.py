"""Read-only plan projections. They never infer procurement or manufacturing probability."""

from collections import defaultdict

from glassflow.contracts.common import Dimensions
from glassflow.contracts.cutting import NewRequirement, NewRequirements, PlacementMargin, PlanMargins

from .domain import GAP_MM, NEW, TEMPERED_TOLERANCE_MM, TRIM_MM, Assignment, Snapshot, oriented_size
from .eligibility import REASON_RU


def new_requirements(snapshot: Snapshot, assignments: list[Assignment], reasons: dict[str, str], *,
                     plan_id: str, revision: int, plan_status: str, is_active: bool,
                     inventory_version: str) -> NewRequirements:
    groups = defaultdict(list)
    for assignment in assignments:
        if assignment.remnant_id == NEW:
            part = snapshot.parts[assignment.part_id]
            reason = reasons.get(part.part_id, 'UNKNOWN_REASON')
            groups[(part.material_id, part.length_mm, part.width_mm, reason)].append(part)
    rows = []
    for (material_id, length, width, reason), parts in sorted(groups.items()):
        rows.append(NewRequirement(material_id=material_id,
            dimensions=Dimensions(length_mm=length, width_mm=width), quantity=len(parts),
            part_ids=sorted(p.part_id for p in parts), order_ids=sorted({p.order_id for p in parts}),
            area_mm2=sum(p.area for p in parts), reason_code=reason,
            reason_ru=REASON_RU.get(reason, 'Причина не сохранена; NEW не доказывает невозможность раскроя.')))
    return NewRequirements(dataset_id=snapshot.dataset_id, plan_id=plan_id, revision=revision,
        plan_status=plan_status, is_active=is_active,
        scope='active' if is_active else ('historical' if plan_status == 'superseded' else 'proposal'),
        inventory_version=inventory_version, rows=rows, total_area_mm2=sum(r.area_mm2 for r in rows),
        total_quantity=sum(r.quantity for r in rows))


def geometry_margins(snapshot: Snapshot, assignments: list[Assignment], *, plan_id: str,
                     revision: int, inventory_version: str) -> PlanMargins:
    by_remnant = defaultdict(list)
    for a in assignments:
        if a.remnant_id != NEW:
            by_remnant[a.remnant_id].append(a)
    rows = []
    for rid, group in sorted(by_remnant.items()):
        remnant = snapshot.remnants[rid]
        for a in group:
            part = snapshot.parts[a.part_id]
            width, height = oriented_size(part, a.rot or 0)
            if snapshot.is_tempered(part.material_id):
                deviation = max(abs(width-remnant.length_mm), abs(height-remnant.width_mm))
                rows.append(PlacementMargin(part_id=a.part_id, remnant_id=rid, tempered=True,
                    margin_kind='whole_piece_tolerance', minimum_excess_mm=TEMPERED_TOLERANCE_MM-deviation,
                    dimension_deviation_mm=deviation))
                continue
            x, y = a.x_mm, a.y_mm
            edge = min(x, y, remnant.length_mm-x-width, remnant.width_mm-y-height)
            neighbor = None
            for other in group:
                if other.part_id == a.part_id:
                    continue
                ow, oh = oriented_size(snapshot.parts[other.part_id], other.rot or 0)
                gap = max(other.x_mm-x-width, x-other.x_mm-ow, other.y_mm-y-height, y-other.y_mm-oh)
                neighbor = gap if neighbor is None else min(neighbor, gap)
            excess = min(edge-TRIM_MM, neighbor-GAP_MM) if neighbor is not None else edge-TRIM_MM
            rows.append(PlacementMargin(part_id=a.part_id, remnant_id=rid, tempered=False,
                margin_kind='cut_geometry', edge_clearance_mm=edge, neighbor_clearance_mm=neighbor,
                minimum_excess_mm=excess))
    return PlanMargins(dataset_id=snapshot.dataset_id, plan_id=plan_id, revision=revision,
        inventory_version=inventory_version, placements=rows)
