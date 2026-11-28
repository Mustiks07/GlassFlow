"""Live-found defect (critical x3, 28.11.2026): the model named the glass line as the whole price.

Answers below are verbatim model outputs from docs/ai/evidence/live/
live_critical_x3_gemini-3.5-flash-lite_after_f4.json (E027 r1, E028 r0). Expected totals are
computed by hand from the KB: 6 mm clear glass 8 000 ₸/м², euro edge 400 ₸/м (rule r4).
"""

from decimal import Decimal

from glassflow.modules.intelligence.assistant.facts import FactSet
from glassflow.modules.intelligence.assistant.verifier import verify_answer
from glassflow.modules.intelligence.evaluation.live import evaluate_live

from .conftest import PACK
from .fakes import reply, tool_call
from .test_live_acceptance import _runtime

E027_R1 = ("Предварительная стоимость стекла 6 мм прозрачное (размером 451×370 мм) составляет 1334.96 ₸ "
           "(включая обработку кромки по периметру). Уточните, пожалуйста, требуется ли вам дополнительная обработка?")
E028_R0 = "Предварительная стоимость стекла 6 мм прозрачного (450×370 мм, 2 шт., с обработкой кромки по периметру) составляет 2 664 ₸."


def _quote(lines, total, dims=(451, 370)):
    facts = FactSet()
    for amount in lines:
        facts.add("line", Decimal(amount), "₸", "pricing:x")
    facts.add("total", Decimal(total), "₸", "pricing:total")
    for dim in dims:
        facts.add("dimension", dim, "мм", "input")
    facts.add_quote([Decimal(a) for a in lines], Decimal(total))
    return facts


def test_line_named_without_total_is_unsupported():
    facts = _quote(["1334.96", "656.80"], "1991.76")
    result = verify_answer(E027_R1, facts, "451 на 370 мм, стекло 6мм прозрачное, кромка по периметру")
    assert result.status == "unsupported" and "claim:incomplete_total:1991.76" in result.unsupported


def test_quantity_line_without_total_is_unsupported():
    facts = _quote(["2664", "1312"], "3976", dims=(450, 370))
    facts.add("quantity", 2, "шт", "input")
    result = verify_answer(E028_R0, facts, "стекло 6мм прозрачное 450x370 кромка по периметру 2 штуки")
    assert "claim:incomplete_total:3976" in result.unsupported


def test_complete_answers_pass():
    facts = _quote(["1334.96", "656.80"], "1991.76")
    for text in ("Стекло 451×370 мм — 1 334,96 ₸, кромка — 656,80 ₸, итого 1 991,76 ₸.",
                 "Итого предварительно 1 991,76 ₸ за стекло с кромкой по периметру."):
        # Complete amounts still need the subject/unit provenance required by C3-F5.
        assert verify_answer(text, facts, "451 на 370").status == "unsupported"
        reference = facts.claim(text, source_ref="renderer:pricing")
        assert verify_answer(reference, facts, "451 на 370").status == "supported"


def test_single_line_quote_has_no_completeness_rule():
    facts = FactSet()
    facts.add("line", Decimal("1332"), "₸", "pricing:glass")
    facts.add_quote([Decimal("1332")], Decimal("1332"))
    assert facts.quotes == []
    reference = facts.claim("Стекло — 1 332 ₸.", source_ref="renderer:pricing")
    assert verify_answer(reference, facts).status == "supported"


def test_incomplete_model_answer_falls_back_to_the_full_deterministic_quote(tmp_path):
    script = [
        reply(tool_call("calculate_quote", {"catalog_product_id": "steklo-6-prozrachnoe", "length_mm": 450, "width_mm": 370,
                                            "quantity": 2, "processing": "euro_edge", "edge_sides": "all"}),
              model="gemini-3.5-flash-lite"),
        reply(tool_call("submit_answer", {"answer_ru": E028_R0}), model="gemini-3.5-flash-lite"),
    ]
    override, _ = _runtime(script)
    report = evaluate_live(PACK, tmp_path, model=None, case_ids=["E028"], runtime_override=override, run_preflight=False)
    run = report["results"][0]
    assert run["llm_status"] == "verifier_rejected" and run["answer_path"] == "fallback"
    assert "3 976" in run["answer"] or "3976" in run["answer"]
    acc = report["acceptance"]  # the client saw the right total, but the model's answer was wrong
    assert acc["status"] == "FAIL" and acc["online_runs"] == 1 and acc["online_ok"] == 0
    assert acc["verifier_rejected_model_answers"] == 1
