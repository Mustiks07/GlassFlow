"""Material valuation helpers for neighbours (C2 metrics, Pro sale cards).

Purpose-separated from the client catalog on purpose: the materials.csv rate values a
warehouse piece; it never selects or prices a catalog product (e.g. mirror-4 at 9 500 ₸/m²
does not pick one of the two catalog mirror formats). Exact Decimal; one rounding at the end.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
MIN_FACTOR = Decimal("0.30")
MAX_FACTOR = Decimal("0.70")


@dataclass(frozen=True)
class Valuation:
    purpose: str  # material_replacement_valuation | remnant_card_price
    area_mm2: int
    rate_per_m2: Decimal
    factor: Decimal
    exact_tg: Decimal
    amount_tg: Decimal  # ROUND_HALF_UP to 0.01


def material_replacement_valuation(area_mm2: int, rate_per_m2: Decimal) -> Valuation:
    """Sum of part areas covered from remnants × materials.csv rate (an estimate, not profit)."""
    if isinstance(area_mm2, bool) or not isinstance(area_mm2, int) or area_mm2 < 0:
        raise ValueError("area_mm2 must be a non-negative integer")
    exact = Decimal(area_mm2) / Decimal(1_000_000) * Decimal(rate_per_m2)
    return Valuation("material_replacement_valuation", area_mm2, Decimal(rate_per_m2), Decimal(1), exact, exact.quantize(CENT, ROUND_HALF_UP))


def remnant_card_price(length_mm: int, width_mm: int, rate_per_m2: Decimal, factor: Decimal = Decimal("0.50")) -> Valuation:
    """Full original remnant area × materials rate × factor in [0.30, 0.70], bounds checked after rounding."""
    factor = Decimal(factor)
    if not MIN_FACTOR <= factor <= MAX_FACTOR:
        raise ValueError("factor must be within 0.30–0.70")
    if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in (length_mm, width_mm)):
        raise ValueError("dimensions must be positive integer millimetres")
    area = length_mm * width_mm
    full = Decimal(area) / Decimal(1_000_000) * Decimal(rate_per_m2)
    exact = full * factor
    amount = exact.quantize(CENT, ROUND_HALF_UP)
    low, high = full * MIN_FACTOR, full * MAX_FACTOR
    if amount < low:
        amount = (low / CENT).to_integral_value(rounding="ROUND_CEILING") * CENT
    if amount > high:
        amount = (high / CENT).to_integral_value(rounding="ROUND_FLOOR") * CENT
    return Valuation("remnant_card_price", area, Decimal(rate_per_m2), factor, exact, amount)
