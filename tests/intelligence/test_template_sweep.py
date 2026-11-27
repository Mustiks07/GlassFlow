"""Generalization sweep: the open-set question/dialog templates applied to EVERY KB product.

Synthetic test data generated from the KB JSON itself (expected values read straight from
the raw JSON, independent of the parser). Guards against an engine tuned to the 18 open
questions only. Not organisers' hidden data.
"""

import json
import re

import pytest

from glassflow.modules.intelligence.quality.dialogs import check_dialog

from .conftest import KB_PATH, numbers_in

RAW = json.loads(KB_PATH.read_text(encoding="utf-8"))["товары"]
HARDWARE = [item for item in RAW if item["вид"] == "hardware"]
MATERIALS = [item for item in RAW if item["вид"] == "material"]


def _has(answer: str, value: float, tolerance: float = 0.5) -> bool:
    return any(abs(got - value) <= tolerance for got in numbers_in(answer))


def _lower_first(name: str) -> str:
    return name[0].lower() + name[1:]


@pytest.mark.parametrize("item", HARDWARE, ids=lambda i: i["id"])
def test_hardware_tiers_for_every_item(engine, item):
    retail, bulk = item["цена_розница_тг"], item["цена_от_100_шт_тг"]
    for question in (f"Почём {item['название']} в розницу и при заказе от 100 штук?", f"Сколько стоит {item['название']}?"):
        answer = engine.respond(question).answer
        assert retail is None or _has(answer, retail), (question, answer)
        assert bulk is None or _has(answer, bulk), (question, answer)
        if bulk is None:
            assert "менеджер" in answer


@pytest.mark.parametrize("item", MATERIALS, ids=lambda i: i["id"])
def test_material_rate_sheet_and_compute_for_every_item(engine, item):
    name, rate, sheet = item["название"], item["цена_за_м2_тг"], item["цена_листа_тг"]
    per_m2 = engine.respond(f"Сколько стоит {name} за квадратный метр?").answer
    assert _has(per_m2, rate) if rate is not None else "менеджер" in per_m2, per_m2
    whole = engine.respond(f"Какая цена целого листа: {name}?").answer
    assert _has(whole, sheet) if sheet is not None else "менеджер" in whole, whole
    for length, width in ((1200, 1800), (700, 1500), (451, 370)):
        answer = engine.respond(f"Нужно {_lower_first(name)} размером {length}×{width} мм. Сколько это стоит по цене за м²?").answer
        if rate is None:
            assert "менеджер" in answer
            continue
        expected = length * width / 1_000_000 * rate
        assert _has(answer, expected, max(2, expected * 0.005)), answer


@pytest.mark.parametrize("item", RAW, ids=lambda i: i["id"])
def test_dialog_ok_and_error_for_every_item(kb, item):
    price = item.get("цена_за_м2_тг") if item["вид"] == "material" else item.get("цена_розница_тг")
    if price is None:
        pytest.skip("no unit price in KB")
    name = item["название"]
    for manager_name in (name, re.sub(r"[,()]", "", name)):  # manager may drop punctuation
        ok = check_dialog(kb, "S", f"Почём {_lower_first(name)}?", f"Здравствуйте! {manager_name}: {price:,} тг.".replace(",", " "))
        assert ok.verdict == "OK", (name, ok)
        wrong = check_dialog(kb, "S", f"Сколько стоит {name}?", f"Здравствуйте! {manager_name}: {price + 1000:,} тг.".replace(",", " "))
        assert (wrong.verdict, float(wrong.correct)) == ("ERROR", float(price)), (name, wrong)
