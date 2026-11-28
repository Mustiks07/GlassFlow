"""Author regressions, separate from the sealed independent examiner."""

import pytest


@pytest.mark.parametrize("text", [
    "Рифленое прозрачное 8 мм, деталь 400×300 мм, 2 шт., сколько стоит?",
    "Рифленое прозрачное 8 мм за квадратный метр",
])
def test_manager_priced_items_do_not_ask_parameters_that_cannot_unlock_a_price(engine, text):
    result = engine.respond(text)
    assert result.status == "manager_handoff"
    assert "менеджер" in result.answer.lower()
    assert "уточните" not in result.answer.lower()
    assert result.clarification is None


@pytest.mark.parametrize("text,total", [
    ("Стекло 6 мм прозрачное 450×370 мм, 1 шт., евро-кромка по всем сторонам", "1988.00"),
    ("Стекло 6 мм прозрачное 45×37 см, 1 шт., евро-кромка по всем сторонам", "1988.00"),
    ("Стекло 6 мм прозрачное 0,45×0,37 м, 1 шт., евро-кромка по всем сторонам", "1988.00"),
])
def test_complete_dimensions_keep_full_calculation_without_extra_question(engine, text, total):
    result = engine.respond(text)
    assert result.clarification is None and result.status == "answered"
    assert str(result.pricing.total) == total


def test_only_unknown_edge_choice_is_asked_and_answer_is_not_invented(engine):
    result = engine.respond("Стекло 6 мм прозрачное 450×370 мм, 2 шт., кромка по выбранным сторонам")
    assert result.missing_parameters == ["edge_sides"]
    assert result.context.length_mm == 450 and result.context.quantity == 2
    assert result.context.edge_sides == "selected" and not result.context.selected_sides
    assert result.status == "clarification"


def test_ambiguous_decimal_unit_is_not_hidden_by_edge_only_intent(engine):
    result = engine.respond("Стекло 6 мм прозрачное 0,45×0,37, кромка по всем сторонам")
    assert result.status == "clarification"
    assert result.missing_parameters == ["dimensions_unit"]
    assert result.context.length_mm is None
    assert result.pricing is None
