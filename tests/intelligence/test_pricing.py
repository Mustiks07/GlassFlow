"""Exact Pricing: control values from the TZ, thresholds, unknown prices, property checks."""

from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from glassflow.modules.intelligence.pricing import PricingInput, PricingInputError, calculate


def run(kb, product_id, *args, **kwargs):
    return calculate(kb, PricingInput(kb.product(product_id), *args, **kwargs))


def amounts(result):
    return {line.component: f"{line.amount:f}" for line in result.lines}


def test_t28_450x370_clear6_all_edges(kb):
    result = run(kb, "steklo-6-prozrachnoe", 450, 370, 1, "euro_edge", "all")
    assert amounts(result) == {"glass": "1332.00", "edge": "656.00"}
    assert f"{result.total:f}" == "1988.00"
    assert result.complete


def test_t28_451x370_changes_glass_and_edge(kb):
    result = run(kb, "steklo-6-prozrachnoe", 451, 370, 1, "euro_edge", "all")
    assert amounts(result) == {"glass": "1334.96", "edge": "656.80"}
    assert f"{result.total:f}" == "1991.76"


def test_t28_quantity_two_doubles_glass_and_processing(kb):
    result = run(kb, "steklo-6-prozrachnoe", 450, 370, 2, "euro_edge", "all")
    assert amounts(result) == {"glass": "2664.00", "edge": "1312.00"}
    assert f"{result.total:f}" == "3976.00"


def test_t27_patterned_8_sheet_known_part_unknown_then_clear8(kb):
    patterned = run(kb, "riflenoe-prozrachnoe-8", 500, 500, 1)
    assert patterned.total is None and patterned.lines == []
    assert patterned.unknowns[0].reason_code == "per_m2_price_not_in_kb"
    assert kb.product("riflenoe-prozrachnoe-8").price("per_sheet").amount == Decimal("170000")
    clear = run(kb, "steklo-8-prozrachnoe", 500, 500, 1)
    assert f"{clear.total:f}" == "3000.00"


def test_t29_hardware_threshold_99_vs_100(kb):
    assert f"{run(kb, 'polkoderzhatel-19-15-16', quantity=99).total:f}" == "14850.00"
    assert f"{run(kb, 'polkoderzhatel-19-15-16', quantity=100).total:f}" == "10000.00"


def test_t29_unknown_quantity_shows_both_tiers(kb):
    result = run(kb, "polkoderzhatel-19-15-16", quantity=None)
    assert result.total is None
    assert {tier.price_type: tier.amount for tier in result.tiers} == {
        "retail_unit": Decimal("150"),
        "bulk_unit": Decimal("100"),
    }


def test_t29_missing_bulk_price_is_not_replaced_by_retail(kb):
    result = run(kb, "lupa", quantity=100)
    assert result.total is None
    assert result.unknowns[0].reason_code == "price_not_in_kb"


def test_t29_sheet_price_never_derives_per_m2(kb):
    result = run(kb, "riflenoe-seroe-8", 1000, 1000, 1, price_basis="per_m2")
    assert result.total is None
    sheet = run(kb, "riflenoe-seroe-8", price_basis="per_sheet")
    assert f"{sheet.total:f}" == "200000.00"


def test_t26_grey_without_thickness_and_grey8_are_distinct(kb):
    assert f"{run(kb, 'steklo-seroe', 1000, 1000, 1).total:f}" == "10000.00"
    assert f"{run(kb, 'steklo-seroe-8', 1000, 1000, 1).total:f}" == "20000.00"


def test_edge_rates_only_from_kb_rule(kb):
    unknown = run(kb, "riflenoe-prozrachnoe-5", 500, 500, 1, "euro_edge", "all")
    assert any(u.reason_code == "edge_rate_not_in_kb" for u in unknown.unknowns)
    assert unknown.total is None and unknown.known_subtotal is not None
    no_thickness = run(kb, "steklo-seroe", 500, 500, 1, "euro_edge", "all")
    assert any(u.reason_code == "thickness_unknown" for u in no_thickness.unknowns)
    four = run(kb, "steklo-4-prozrachnoe", 1000, 500, 1, "euro_edge", "all")
    assert amounts(four)["edge"] == "900.00"


@pytest.mark.parametrize("kind", ["facet", "sandblast"])
def test_facet_and_sandblast_have_no_price(kb, kind):
    result = run(kb, "steklo-6-prozrachnoe", 500, 500, 1, kind)
    assert result.total is None
    assert result.unknowns[0].reason_code == "processing_price_not_in_kb"


def test_partial_sides_count_only_confirmed_sides(kb):
    result = run(kb, "steklo-6-prozrachnoe", 450, 370, 1, "euro_edge", "selected", ("top",))
    assert amounts(result)["edge"] == "180.00"
    empty = run(kb, "steklo-6-prozrachnoe", 450, 370, 1, "euro_edge", "selected", ())
    assert any(u.reason_code == "edge_sides_unknown" for u in empty.unknowns)


@pytest.mark.parametrize(
    "kwargs",
    [dict(quantity=0), dict(quantity=-1), dict(quantity=True), dict(length_mm=100, width_mm=None), dict(length_mm=0, width_mm=10)],
)
def test_invalid_inputs_are_rejected(kb, kwargs):
    with pytest.raises(PricingInputError):
        calculate(kb, PricingInput(kb.product("steklo-6-prozrachnoe"), **kwargs))


@settings(max_examples=200, deadline=None)
@given(
    length=st.integers(min_value=1, max_value=6000),
    width=st.integers(min_value=1, max_value=4000),
    quantity=st.integers(min_value=1, max_value=500),
    product_id=st.sampled_from(["steklo-4-prozrachnoe", "steklo-6-prozrachnoe", "zerkalo-4-list-2750"]),
)
def test_property_total_equals_sum_of_rounded_lines(kb, length, width, quantity, product_id):
    result = run(kb, product_id, length, width, quantity, "euro_edge", "all")
    assert result.total == sum(line.amount for line in result.lines)
    for line in result.lines:
        assert line.amount == line.exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert line.amount.as_tuple().exponent == -2
    product = kb.product(product_id)
    rate = product.price("per_m2").amount
    assert result.lines[0].exact == Decimal(length * width) / Decimal(1_000_000) * rate * quantity
