"""Pure cutting domain objects used by the validator and the solver.

These are deliberately plain frozen dataclasses (no ORM, no Pydantic) so the solver worker can
receive a serialisable snapshot and run without a database. Geometry is integer millimetres,
money is ``Decimal``. External IDs from CSV are kept verbatim; uniqueness is scoped to one snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

TRIM_MM = 5
"""Edge trim of an ordinary remnant (case rules, validate.py ``TRIM``)."""
GAP_MM = 3
"""Kerf: minimal axis-separation between two parts on one remnant (validate.py ``GAP``)."""
TEMPERED_TOLERANCE_MM = 2
"""Tempered glass cannot be cut: each dimension must match within ±2 mm (validate.py ``TOL``)."""
NEW = "NEW"
"""Marker of a part not covered by a remnant. Not a commercial product, not proof of impossibility."""


@dataclass(frozen=True, slots=True)
class MaterialSpec:
    material_id: str
    tempered: bool
    price_per_m2: Decimal
    name: str = ""
    thickness_mm: int = 0


@dataclass(frozen=True, slots=True)
class RemnantSpec:
    remnant_id: str
    material_id: str
    length_mm: int
    width_mm: int
    defect: bool
    age_days: int | None = None
    status: str = "available"
    version: int = 0
    location_raw: str = ""
    original: bool = True

    @property
    def area(self) -> int:
        return self.length_mm * self.width_mm


@dataclass(frozen=True, slots=True)
class PartSpec:
    part_id: str
    order_id: str
    material_id: str
    length_mm: int
    width_mm: int
    premium: bool
    product_type: str = ""

    @property
    def area(self) -> int:
        return self.length_mm * self.width_mm


@dataclass(frozen=True, slots=True)
class Assignment:
    """One row of a plan. ``remnant_id == NEW`` means not covered by stock."""

    part_id: str
    remnant_id: str
    x_mm: int | None = None
    y_mm: int | None = None
    rot: int | None = None
    lock_kind: str = "none"


@dataclass(slots=True)
class Snapshot:
    dataset_id: str
    materials: dict[str, MaterialSpec]
    remnants: dict[str, RemnantSpec]
    parts: dict[str, PartSpec]
    part_order: list[str] = field(default_factory=list)
    remnant_order: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.part_order:
            self.part_order = list(self.parts)
        if not self.remnant_order:
            self.remnant_order = list(self.remnants)

    @property
    def total_part_area(self) -> int:
        return sum(p.area for p in self.parts.values())

    def is_tempered(self, material_id: str) -> bool:
        material = self.materials.get(material_id)
        return bool(material and material.tempered)


def oriented_size(part: PartSpec, rot: int) -> tuple[int, int]:
    """(w along x / remnant length, h along y / remnant width). rot=1 swaps the part sides."""
    return (part.width_mm, part.length_mm) if rot else (part.length_mm, part.width_mm)


def tempered_orientation(part: PartSpec, remnant: RemnantSpec) -> int | None:
    """Orientation (0/1) in which the whole tempered remnant matches the part within ±2 mm."""
    tol = TEMPERED_TOLERANCE_MM
    if abs(part.length_mm - remnant.length_mm) <= tol and abs(part.width_mm - remnant.width_mm) <= tol:
        return 0
    if abs(part.length_mm - remnant.width_mm) <= tol and abs(part.width_mm - remnant.length_mm) <= tol:
        return 1
    return None


def ordinary_fits(part: PartSpec, remnant: RemnantSpec) -> list[int]:
    """Orientations in which a single part fits inside the trimmed working area."""
    usable_l = remnant.length_mm - 2 * TRIM_MM
    usable_w = remnant.width_mm - 2 * TRIM_MM
    result = []
    for rot in (0, 1):
        w, h = oriented_size(part, rot)
        if w <= usable_l and h <= usable_w:
            result.append(rot)
    return result
