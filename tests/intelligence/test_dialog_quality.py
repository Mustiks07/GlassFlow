"""Dialog price control (T37–T39): context meaning of numbers, KB references, no KEY."""

import pytest

from glassflow.modules.intelligence.quality.dialogs import check_dialog


@pytest.mark.parametrize(
    ("client", "manager", "verdict", "correct"),
    [
        ("Почём калёное стекло серое?", "Здравствуйте! Калёное стекло серое: 15 500 тг.", "OK", None),
        (
            "Сколько стоит Bluetooth-динамик + переключатель одинарный YZKJ-Y2-24BLE?",
            "Здравствуйте! Bluetooth-динамик + переключатель одинарный YZKJ-Y2-24BLE: 10 050 тг.",
            "ERROR",
            "10000",
        ),
        ("Почём стекло серое?", "Здравствуйте! Стекло серое: 13 000 тг.", "ERROR", "10000"),
        ("Сколько стоит Подвес для скрытого крепления зеркала?", "Здравствуйте! Подвес для скрытого крепления зеркала: 700 тг.", "ERROR", "400"),
        (
            "Сколько стоит Навес для алюминиевых фасадов 20 × 20, 3D, чёрный?",
            "Здравствуйте! Навес для алюминиевых фасадов 20 × 20, 3D, чёрный: 500 тг.",
            "OK",
            None,
        ),
    ],
)
def test_open_regression_examples_by_content(kb, client, manager, verdict, correct):
    # Synthetic IDs on purpose: the verdict must follow the text, not a table of known IDs.
    result = check_dialog(kb, "SYNTH-1", client, manager)
    assert result.verdict == verdict
    assert result.correct == correct


def test_t38_model_code_and_sizes_are_not_prices(kb):
    result = check_dialog(
        kb,
        "X",
        "Сколько стоит Bluetooth-динамик YZKJ-Y2-24BLE?",
        "Bluetooth-динамик + переключатель одинарный YZKJ-Y2-24BLE (24 Вт, 120×80 мм): 10 050 тг.",
    )
    assert result.verdict == "ERROR" and result.correct == "10000"
    assert [m.amount_tg for m in result.mentions] == ["10050"]


def test_same_id_different_text_changes_result(kb):
    wrong = check_dialog(kb, "D07", "Почём стекло серое?", "Стекло серое: 13 000 тг.")
    right = check_dialog(kb, "D07", "Почём стекло серое?", "Стекло серое: 10 000 тг.")
    assert (wrong.verdict, right.verdict) == ("ERROR", "OK")
    assert wrong.input_sha256 != right.input_sha256


def test_price_meaning_rate_sheet_retail_bulk_total(kb):
    assert check_dialog(kb, "a", "Почём стекло серое 8 мм?", "20 000 тг за м², лист 90 000 тг.").verdict == "OK"
    sheet_wrong = check_dialog(kb, "b", "Почём лист стекла серого 8 мм?", "Целый лист — 20 000 тг.")
    assert (sheet_wrong.verdict, sheet_wrong.correct) == ("ERROR", "90000")
    bulk_wrong = check_dialog(kb, "c", "Почём уголок большой для рамочного фасада?", "450 тг в розницу, от 100 шт — 300 тг.")
    assert (bulk_wrong.verdict, bulk_wrong.correct) == ("ERROR", "350")
    total = check_dialog(kb, "d", "Сколько стоит стекло 6 мм прозрачное 1200×1800?", "Получится 17 280 тг за деталь.")
    assert total.verdict == "OK"
    total_wrong = check_dialog(kb, "e", "Сколько стоит стекло 6 мм прозрачное 1200×1800?", "Выйдет 18 000 тг.")
    assert (total_wrong.verdict, total_wrong.correct) == ("ERROR", "17280")


def test_absolute_tolerance_half_tenge(kb):
    assert check_dialog(kb, "a", "Почём стекло серое?", "10 000,40 тг").verdict == "OK"
    assert check_dialog(kb, "b", "Почём стекло серое?", "10 001 тг").verdict == "ERROR"


def test_unknowns_stay_needs_review_or_follow_kb_rule(kb):
    ab = check_dialog(kb, "a", "Почём зеркало AB1020?", "Зеркало AB1020 стоит 25 000 тг.")
    assert ab.verdict == "OK" and ab.reason_code == "price_set_by_manager_per_kb_rule"
    unknown = check_dialog(kb, "b", "Сколько стоит стеклопакет?", "Стеклопакет: 30 000 тг.")
    assert unknown.verdict == "NEEDS_REVIEW"
    no_price = check_dialog(kb, "c", "Почём стекло серое 8 мм?", "Уточню у менеджера.")
    assert no_price.verdict == "OK"


def test_ambiguous_question_wrong_for_every_candidate_is_needs_review(kb):
    # Changed after review F1: the earlier version of this test asserted a best-ranked correction,
    # which invented certainty. A correction is exported only when all interpretations prove it.
    right = check_dialog(kb, "a", "Почём зеркало 4 мм?", "Зеркало 4 мм: 11 500 тг.")
    assert right.verdict == "OK" and right.catalog_product_id == "zerkalo-4-list-3210"
    wrong = check_dialog(kb, "b", "Почём зеркало 4 мм?", "Зеркало 4 мм: 10 000 тг.")
    assert wrong.verdict == "NEEDS_REVIEW" and wrong.correct is None
    assert wrong.reason_code == "ambiguous_product_correction_not_unique"
