"""Evaluator regressions, not a product acceptance substitute."""

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("review_exam", HERE.parents[1] / "scripts/post_review_exam.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)
EXAM = json.loads((HERE / "ai_exam_v1.json").read_text(encoding="utf8"))


def test_frozen_exam_covers_independent_families_and_critical_repeats():
    cases = EXAM["cases"]
    assert len(cases) >= 60 and len({c["id"] for c in cases}) == len(cases)
    assert EXAM["critical_repeats"] == 3 and sum(c["critical"] for c in cases) >= 12
    assert {
        "changed_KB",
        "removed_KB_price",
        "sheet_unit",
        "bulk_boundary",
        "unknown_price",
        "ambiguity",
        "commercial_binding_adversarial",
        "units_and_wording",
    } <= {c["family"] for c in cases}


def test_right_total_for_wrong_product_cannot_pass():
    case = EXAM["cases"][0]
    expected = case["expected"]["quote"]
    reply = {
        "status": "answered",
        "answer": f"Итого {expected['total_tg']} тенге.",
        "quote": {
            "catalog_product_id": "wrong-product",
            "quantity": expected["quantity"],
            "dimensions": expected["dimensions"],
            "total_tg": expected["total_tg"],
        },
    }
    assert not review.grade(case, reply)["ok"]


def test_complete_request_refusal_is_not_credited_as_safe_accuracy():
    result = review.grade(EXAM["cases"][0], {"status": "manager_handoff", "answer": "Все уточнит менеджер."})
    assert not result["ok"] and result["unnecessary_refusal"]


def test_unknown_price_is_not_allowed_to_be_zero():
    case = next(c for c in EXAM["cases"] if c["family"] == "removed_KB_price")
    result = review.grade(
        case,
        {
            "status": "manager_handoff",
            "answer": "Цена0тенге, спросите менеджера.",
            "quote": {"total_tg": "0"},
        },
    )
    assert not result["ok"] and result["fabrication"]


def test_cached_or_unconfirmed_model_reply_does_not_raise_live_accuracy():
    reply = {"answer_path": "llm_tools", "provider": "gemini", "model_id": "selected"}
    result = review.provenance(reply, {"calls": 10, "ok": 9}, {"calls": 10, "ok": 9}, "gemini:selected")
    assert result["origin"] == "cache_or_unverifiable" and not result["selected_model_answer_confirmed"]


def test_fallback_after_rejection_is_a_failed_model_attempt():
    reply = {"answer_path": "fallback", "verifier_status": "unsupported_replaced"}
    result = review.provenance(reply, {"calls": 0, "ok": 0}, {"calls": 2, "ok": 2}, "gemini:selected")
    assert result["verifier_rejected_attempt"] and not result["selected_model_answer_confirmed"]


def test_required_edge_total_cannot_be_replaced_by_its_glass_line():
    case = next(
        c for c in EXAM["cases"] if c["expected"].get("quote", {}).get("components_tg", {}).get("edge")
    )
    expected = case["expected"]["quote"]
    reply = {
        "status": "answered",
        "answer": f"За стекло с кромкой {expected['components_tg']['glass']} тенге.",
        "quote": {
            "catalog_product_id": expected["product_id"],
            "quantity": expected["quantity"],
            "dimensions": expected["dimensions"],
            "total_tg": expected["total_tg"],
        },
    }
    result = review.grade(case, reply)
    assert result["incomplete"] and not result["ok"]


def test_optional_quote_and_qualified_bulk_information_are_not_false_fabrication():
    case = next(c for c in EXAM["cases"] if c["family"] == "bulk_boundary")
    expected = case["expected"]["quote"]
    reply = {
        "status": "answered",
        "answer": f"99 шт × 450 тенге = {expected['total_tg']} тенге. При заказе от 100 шт — 350 тенге за штуку.",
        "card": {"catalog_product_id": expected["product_id"], "confirmed_parameters": {"quantity": "99"}},
    }
    assert review.grade(case, reply)["ok"]
    reply["answer"] += " Дополнительная стоимость 99999 тенге."
    assert review.grade(case, reply)["fabrication"]


def test_inapplicable_product_selection_is_a_commercial_failure_even_without_quote():
    case = next(c for c in EXAM["cases"] if c["family"] == "ambiguity" and "переключатель" in c["question"])
    reply = {"status": "answered", "answer": "Двойной переключатель: 5 шт × 2000 тенге = 10000 тенге."}
    assert review.grade(case, reply)["fabrication"]


def test_true_total_is_not_proof_of_a_unit_rate_for_the_same_amount():
    case = EXAM["cases"][0]
    expected = case["expected"]["quote"]
    reply = {
        "status": "answered",
        "answer": f"Итого {expected['total_tg']} тенге. Ставка {expected['total_tg']} тенге за м².",
        "quote": {
            "catalog_product_id": expected["product_id"],
            "quantity": expected["quantity"],
            "dimensions": expected["dimensions"],
            "total_tg": expected["total_tg"],
        },
    }
    assert review.grade(case, reply)["fabrication"]


def test_missing_area_rate_cannot_be_filled_with_known_sheet_price():
    case = next(c for c in EXAM["cases"] if c["family"] == "unknown_price")
    reply = {"status": "manager_handoff", "answer": "Цена 170000 тенге за м². Подтвердит менеджер."}
    assert review.grade(case, reply)["fabrication"]
