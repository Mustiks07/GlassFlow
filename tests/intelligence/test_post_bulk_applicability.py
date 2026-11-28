"""Shared canonical QA tariff applicability, not a numeric catalogue whitelist."""

import pytest

from glassflow.modules.intelligence.quality.dialogs import check_dialog


@pytest.mark.parametrize("quantity", [3, 99])
@pytest.mark.parametrize("price", [100, 500])
def test_unqualified_bulk_rate_is_not_applicable_below_threshold(kb, quantity, price):
    result = check_dialog(kb, f"qty-{quantity}", f"Нужно {quantity} шт. полкодержатель 19×15×16 мм",
                          f"Оптовая цена {price} тг за штуку.")
    assert result.verdict == "ERROR" and result.correct == "150"
    assert result.reference_meaning == "retail_unit" and result.reason_code == "bulk_threshold_not_met"
    assert all(e.field == "цена_розница_тг" for e in result.evidence)


@pytest.mark.parametrize("quantity", [100, 101])
def test_bulk_rate_is_applicable_at_and_above_threshold(kb, quantity):
    client = f"Нужно {quantity} штук полкодержатель 19×15×16 мм"
    assert check_dialog(kb, "ok", client, "Оптовая цена 100 тг за штуку.").verdict == "OK"
    wrong = check_dialog(kb, "wrong", client, "Оптовая цена 500 тг за штуку.")
    assert wrong.verdict == "ERROR" and wrong.correct == "100" and wrong.reference_meaning == "bulk_unit"


def test_unknown_quantity_cannot_prove_an_unqualified_bulk_rate(kb):
    result = check_dialog(kb, "unknown", "Полкодержатель 19×15×16 мм", "Оптовая цена 100 тг за штуку.")
    assert result.verdict == "NEEDS_REVIEW" and result.correct is None
    assert result.reason_code == "bulk_threshold_unconfirmed"


@pytest.mark.parametrize("quantity", [3, 99])
def test_explicit_qualified_bulk_rate_is_true_as_a_conditional_fact(kb, quantity):
    client = f"Нужно {quantity} штук полкодержатель 19×15×16 мм"
    assert check_dialog(kb, "conditional", client, "От 100 шт — 100 тг за штуку.").verdict == "OK"
    wrong = check_dialog(kb, "conditional-wrong", client, "От 100 шт — 500 тг за штуку.")
    assert wrong.verdict == "ERROR" and wrong.correct == "100" and wrong.reference_meaning == "bulk_unit"


def test_customer_can_ask_about_a_conditional_tariff_without_an_order_quantity(kb):
    client = "Полкодержатель 19×15×16 мм, сколько от 100 шт?"
    assert check_dialog(kb, "question", client, "Оптовая цена 100 тг за штуку.").verdict == "OK"


def test_qualified_bulk_rate_does_not_make_a_small_order_total_correct(kb):
    result = check_dialog(kb, "mixed", "Нужно 3 штуки полкодержатель 19×15×16 мм",
                          "От 100 шт — 100 тг за штуку. Ваши 3 штуки итого 300 тг.")
    assert result.verdict == "ERROR" and result.correct == "450" and result.reference_meaning == "total"


def test_qualification_in_another_clause_cannot_whitelist_unqualified_bulk_price(kb):
    result = check_dialog(kb, "separate", "Нужно 3 штуки полкодержатель 19×15×16 мм",
                          "Оптовая цена 100 тг за штуку. От 100 шт — 100 тг за штуку.")
    assert result.verdict == "ERROR" and result.correct == "150"


def test_a_conditional_threshold_below_catalog_minimum_is_not_supported(kb):
    result = check_dialog(kb, "low-condition", "Нужно 100 штук полкодержатель 19×15×16 мм",
                          "От 99 шт — 100 тг за штуку.")
    assert result.verdict == "NEEDS_REVIEW" and result.correct is None
    assert result.reason_code == "bulk_condition_not_supported"
