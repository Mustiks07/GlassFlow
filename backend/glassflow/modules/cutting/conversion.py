"""Conversions between transport DTOs and pure domain objects (both directions)."""

from __future__ import annotations

from decimal import Decimal

from glassflow.contracts.common import Dimensions
from glassflow.contracts.cutting import Material, Part, Placement, PlanIssue, Remnant, SolveInput

from .domain import Assignment, MaterialSpec, PartSpec, RemnantSpec, Snapshot
from .geometry import Issue


def snapshot_from_input(data: SolveInput) -> Snapshot:
    materials = {
        m.material_id: MaterialSpec(m.material_id, m.tempered, Decimal(m.unit_price_tg), m.name, m.thickness_mm)
        for m in data.materials
    }
    remnants = {}
    for r in data.remnants:
        if r.dataset_id != data.dataset_id:
            raise ValueError(f"DATASET_MISMATCH: remnant {r.remnant_id} belongs to {r.dataset_id}")
        remnants[r.remnant_id] = RemnantSpec(
            r.remnant_id, r.material_id, r.dimensions.length_mm, r.dimensions.width_mm, r.defect, r.age_days,
            r.status, r.version, r.location_raw, r.original,
        )
    parts = {
        p.part_id: PartSpec(p.part_id, p.order_id, p.material_id, p.dimensions.length_mm, p.dimensions.width_mm,
                            p.premium, p.product_type)
        for p in data.parts
    }
    return Snapshot(data.dataset_id, materials, remnants, parts,
                    [p.part_id for p in data.parts], [r.remnant_id for r in data.remnants])


def input_from_snapshot(snapshot: Snapshot, **kwargs) -> SolveInput:
    return SolveInput(
        dataset_id=snapshot.dataset_id,
        materials=[
            Material(material_id=m.material_id, name=m.name, thickness_mm=m.thickness_mm,
                     unit_price_tg=str(m.price_per_m2), tempered=m.tempered)
            for m in snapshot.materials.values()
        ],
        remnants=[
            Remnant(dataset_id=snapshot.dataset_id, remnant_id=r.remnant_id, material_id=r.material_id,
                    dimensions=Dimensions(length_mm=r.length_mm, width_mm=r.width_mm), age_days=r.age_days,
                    defect=r.defect, location_raw=r.location_raw, status=r.status, version=r.version,
                    original=r.original)
            for r in (snapshot.remnants[rid] for rid in snapshot.remnant_order)
        ],
        parts=[
            Part(part_id=p.part_id, order_id=p.order_id, material_id=p.material_id,
                 dimensions=Dimensions(length_mm=p.length_mm, width_mm=p.width_mm), premium=p.premium,
                 product_type=p.product_type)
            for p in (snapshot.parts[pid] for pid in snapshot.part_order)
        ],
        **kwargs,
    )


def to_assignment(p: Placement) -> Assignment:
    return Assignment(p.part_id, p.remnant_id, p.x_mm, p.y_mm, p.rot, p.lock_kind)


def to_placement(a: Assignment) -> Placement:
    return Placement(part_id=a.part_id, remnant_id=a.remnant_id, x_mm=a.x_mm, y_mm=a.y_mm, rot=a.rot,
                     lock_kind=a.lock_kind if a.lock_kind in ("none", "assignment", "placement") else "none")


def to_plan_issue(issue: Issue) -> PlanIssue:
    return PlanIssue(code=issue.code, message_ru=issue.message_ru, part_id=issue.part_id,
                     remnant_id=issue.remnant_id, other_part_id=issue.other_part_id,
                     coordinates=dict(issue.coordinates))
