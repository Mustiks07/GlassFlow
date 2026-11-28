"""Regression tests for independent review findings F1–F3 (docs/reviews/CLAUDE_3_REVIEW_2026-11-27.md).

Expected values are computed by hand from the KB: стекло 6 мм прозрачное 8 000 ₸/м², евро-кромка
6 мм 400 ₸/м (rule r4); зеркало 4 мм 2750×1605 — 9 500 ₸/м², 3210×2250 — 11 500 ₸/м²;
навес для стекла внутренний/внешний — 450 ₸ розница.
"""

import json

import pytest

from glassflow.modules.intelligence.catalog.kb import parse_knowledge_base
from glassflow.modules.intelligence.quality.dialogs import check_dialog

from .conftest import KB_PATH, numbers_in

GLASS = "стекло 6 мм прозрачное"


# ------------------------------------------------------------------ F1
def test_f1_ambiguous_product_without_provable_correction_is_needs_review(kb):
    verdict = check_dialog(kb, "F1", "Почём зеркало 4 мм?", "Цена 99999 тг.")
    assert verdict.verdict == "NEEDS_REVIEW" and verdict.correct is None
    assert verdict.reason_code == "ambiguous_product_correction_not_unique"
    assert "9500" in verdict.explanation_ru and "11500" in verdict.explanation_ru


def test_f1_result_does_not_depend_on_kb_order(kb):
    document = json.loads(KB_PATH.read_text(encoding="utf-8"))
    document["товары"].reverse()
    reversed_kb = parse_knowledge_base(json.dumps(document, ensure_ascii=False).encode("utf-8"))
    for client, manager in [("Почём зеркало 4 мм?", "Цена 99999 тг."), ("Почём зеркало 4 мм?", "Зеркало 4 мм: 11 500 тг.")]:
        a, b = check_dialog(kb, "x", client, manager), check_dialog(reversed_kb, "x", client, manager)
        assert (a.verdict, a.correct, a.catalog_product_id) == (b.verdict, b.correct, b.catalog_product_id)


def test_f1_equal_prices_for_all_interpretations_give_proven_error(kb):
    verdict = check_dialog(kb, "x", "Сколько стоит навес для стекла?", "Навес для стекла: 600 тг.")
    assert (verdict.verdict, verdict.correct, verdict.reason_code) == ("ERROR", "450", "price_mismatch_all_interpretations")


def test_f1_price_fitting_one_interpretation_is_ok(kb):
    verdict = check_dialog(kb, "x", "Почём зеркало 4 мм?", "11 500 тг за м²")
    assert verdict.verdict == "OK" and verdict.catalog_product_id == "zerkalo-4-list-3210"


# ------------------------------------------------------------------ F2
CLIENT_SIDES = [
    (f"Сколько стоит {GLASS} 1200×1800 с кромкой по двум длинным сторонам?", 18720),
    (f"Сколько стоит {GLASS} 1200×1800 с кромкой по двум коротким сторонам?", 18240),
    (f"Сколько стоит {GLASS} 1200×1800 с кромкой по одной длинной стороне?", 18000),
    (f"Сколько стоит {GLASS} 1200×1800 с кромкой по одной длинной и одной короткой стороне?", 18480),
    (f"Сколько стоит {GLASS} 1200×1800 с кромкой по верхней и нижней стороне?", 18240),
    (f"Сколько стоит {GLASS} 1200×1800 с кромкой по всем сторонам?", 19680),
    (f"Сколько стоит {GLASS} 500×500 с кромкой по двум длинным сторонам?", 2400),
    (f"Сколько стоит {GLASS} 1200×1800, 3 шт, с кромкой по двум длинным сторонам?", 56160),
]


@pytest.mark.parametrize(("client", "total"), CLIENT_SIDES)
def test_f2_dialog_reference_uses_stated_sides_and_quantity(kb, client, total):
    ok = check_dialog(kb, "x", client, f"Итого {total} тг.")
    assert ok.verdict == "OK", (client, ok)
    glass_only = 17280 if "1200" in client else 2000
    if "3 шт" in client:
        glass_only *= 3
    wrong = check_dialog(kb, "x", client, f"Итого {glass_only} тг.")
    assert (wrong.verdict, wrong.correct) == ("ERROR", str(total)), (client, wrong)


@pytest.mark.parametrize(("client", "total"), CLIENT_SIDES)
def test_f2_assistant_and_dialog_check_agree(engine, kb, client, total):
    answer = engine.respond(client).answer
    assert total in numbers_in(answer), answer
    assert check_dialog(kb, "x", client, f"Получится {total} тг.").verdict == "OK"


@pytest.mark.parametrize(
    "client",
    [
        f"Сколько стоит {GLASS} 1200×1800 с фацетом?",  # processing price unknown
        f"Сколько стоит {GLASS} 1200×1800 с кромкой?",  # sides not stated
    ],
)
def test_f2_unknown_processing_total_is_not_verified(kb, client):
    verdict = check_dialog(kb, "x", client, "Итого 17280 тг.")
    assert verdict.verdict == "NEEDS_REVIEW" and verdict.correct is None


# ------------------------------------------------------------------ F3
@pytest.mark.parametrize(
    ("manager", "verdict", "correct"),
    [
        ("Итого 17 280 тг; цена за м²: 9000.", "ERROR", "8000"),  # correct total, wrong bare rate
        ("Цена за м² 8 000 ₸, итого 18000.", "ERROR", "17280"),  # wrong bare total, correct rate
        ("8000 тенге за м², итого 17280 тг.", "OK", None),
        ("Итого: 17 280 ₸ (2,16 м² × 8 000 тг/м²).", "OK", None),
        ("Стекло 6 мм прозрачное 1200x1800: 17 280 KZT", "OK", None),
        ("Итого 17280 тг, цена за м² 7 000 тенге", "ERROR", "8000"),
    ],
)
def test_f3_mixed_price_notations_are_all_checked(kb, manager, verdict, correct):
    result = check_dialog(kb, "x", f"Сколько стоит {GLASS} 1200×1800?", manager)
    assert (result.verdict, result.correct) == (verdict, correct), (manager, result)


def test_f3_sizes_codes_and_quantities_are_not_prices(kb):
    result = check_dialog(kb, "x", "Сколько стоит Блок питания DS-100-12?", "Блок питания DS-100-12 стоит 2 500 тг, артикул 100, партия 300 шт.")
    assert result.verdict == "OK" and [m.amount_tg for m in result.mentions] == ["2500"]
    tiers = check_dialog(kb, "x", "Почём уголок большой для рамочного фасада?", "450 ₸ в розницу, от 100 шт — 350 тенге")
    assert tiers.verdict == "OK" and [m.meaning for m in tiers.mentions] == ["retail_unit", "bulk_unit"]
