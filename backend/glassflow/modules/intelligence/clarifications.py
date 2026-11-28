"""Choices are derived from the current KB and deterministic missing parameters."""

import hashlib

from glassflow.contracts.intelligence import ClarificationOption
from glassflow.modules.intelligence.nlu.extract import extract


def options(kb, local, text, conversation_id, turn_index):
    if local.status not in {"clarification", "answered", "manager_handoff"}:
        return []
    result = []

    def add(kind, label, value):
        token = hashlib.sha256(f"{conversation_id}:{turn_index}:{kb.version}:{kind}:{value}".encode()).hexdigest()[:24]
        result.append(ClarificationOption(choice_id=token, kind=kind, label=label, reply_text=value))

    if local.status == "clarification":
        for product in kb.products:
            if product.name in local.alternatives:
                add("product", product.name, product.name)
    if local.intent == "unit_price" and local.product and local.context.price_basis == "auto":
        for basis, label, value in (("per_sheet", "Цена за целый лист", "Цена за целый лист"),
                                    ("per_m2", "Цена за квадратный метр", "Цена за м²")):
            price = local.product.price(basis)
            if price and price.amount is not None:
                add("price_basis", label, value)
    ex = extract(text)
    if "dimensions_unit" in local.missing_parameters and ex.ambiguous_dimensions and not ex.invalid_dimensions:
        raw = ex.ambiguous_dimensions[0]
        for unit, label in (("мм", "Миллиметры"), ("см", "Сантиметры"), ("м", "Метры")):
            add("unit", label, f"Размер {raw} {unit}")
    if any("side" in p for p in local.missing_parameters):
        for label, value in (("Все четыре стороны", "Евро-кромка по всем четырём сторонам"),
                             ("Верх и низ", "Евро-кромка: верх и низ"),
                             ("Лево и право", "Евро-кромка: лево и право")):
            add("sides", label, value)
    return result[:12]
