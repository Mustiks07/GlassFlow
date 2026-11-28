"""C3-F5 regressions: numeric membership is never commercial provenance."""

from decimal import Decimal

import pytest

from glassflow.modules.intelligence.assistant.facts import FactSet
from glassflow.modules.intelligence.assistant.tools import ToolContext, execute_tool
from glassflow.modules.intelligence.assistant.verifier import verify_answer


@pytest.mark.parametrize("answer,question", [
    ("Стекло 6 мм прозрачное стоит 6 ₸ за м².", "Стекло 6 мм по 6 ₸ за м²?"),
    ("Прозрачное 6 мм: 20000 ₸ за м². Серое 8 мм: 8000 ₸ за м².", "Сравните прозрачное 6 мм и серое 8 мм."),
    ("Итого 8000 ₸, цена за м² 17280 ₸.", ""),
    ("Прозрачное 6 мм: 8000 ₸ за лист.", ""),
    ("Количество 17280, стоимость 2 ₸.", "2 штуки"),
    ("Серое 8 мм есть в наличии на складе.", ""),
])
def test_allowed_numbers_do_not_prove_subject_role_unit_or_stock(answer, question):
    facts = FactSet()
    facts.add("price", Decimal("8000"), "tg/m2", "kb:clear-6")
    facts.add("price", Decimal("20000"), "tg/m2", "kb:grey-8")
    facts.add("total", Decimal("17280"), "tg", "pricing:total")
    facts.add("remnant", "R-clear", None, "inventory:R-clear:v1")
    assert verify_answer(answer, facts, question, remnant_checked=True).status == "unsupported"


def test_trusted_rendering_binds_changed_dimensions_quantity_price_and_source(kb, mappings):
    ctx = ToolContext(kb, mappings, "dataset")
    result = execute_tool(ctx, "calculate_quote", {"catalog_product_id": "steklo-6-prozrachnoe",
        "length_mm": 451, "width_mm": 370, "quantity": 2, "processing": "none"})
    assert result.status == "ok"
    reference = "[[quote]]"
    assert verify_answer(reference, ctx.facts).status == "supported"
    rendered = ctx.facts.render(reference)
    assert "451×370" in rendered and "количество 2" in rendered
    assert str(ctx.last_quote.total) in rendered
    assert verify_answer(rendered.replace("451×370", "450×370"), ctx.facts).status == "unsupported"
    assert verify_answer("Серое 8 мм стоит 8000 ₸ за м². " + reference, ctx.facts).status == "unsupported"
    assert verify_answer("[[unknown]]", ctx.facts).status == "unsupported"
