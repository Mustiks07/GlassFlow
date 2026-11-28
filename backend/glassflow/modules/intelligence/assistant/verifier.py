"""verify_answer: check free text against verified facts before it reaches a client.

Flags numbers that are not in the facts or the user's own input, commercial promises the
KB does not support (discounts, deadlines, delivery, installation, availability, compatibility,
payment), and an incomplete quote: a line of a multi-line calculation (glass, edge) named
without the known total — a true number shown as if it were the whole price. ``unknown`` is never upgraded to a fact; any unsupported claim makes the caller fall
back to the deterministic rendering or a manager hand-off.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from .facts import FactSet

_NUMBER = re.compile(r"\d[\d   ]*(?:[.,]\d+)?")
_CLAIMS = [
    ("discount", r"(?<!не )(?<!не обещ)(?:скидк\w*|акци\w*)\s+(?:\d|в\s+\d|до\s+\d|вам|сделаем|дадим|предостав|будет|есть|действ)"),
    ("discount", r"(?:сделаем|дадим|предоставим|оформим)\s+(?:вам\s+)?скидк"),
    ("deadline", r"\b\d+\s*(?:дн|дня|дней|день|час|недел|рабоч)"),
    ("deadline", r"(?<!не )(?:будет готово|изготовим|сделаем)\s+(?:за|к|до|завтра|сегодня)"),
    ("delivery", r"(?<!не )(?:доставим|привез[её]м|отправим|доставка бесплатн)"),
    # KB: delivery and payment are agreed by the manager — a flat «no delivery» is also unsupported
    ("delivery", r"не (?:выполня\w*|осуществля\w*|предоставля\w*|делаем|делает)\s+(?:\w+\s+){0,3}доставк|доставк\w* (?:нет|не (?:выполня|осуществля|предоставля))|не доставля\w*"),
    ("installation", r"(?<!не )(?:установим|смонтируем|выполним монтаж|приедем|мастер приедет)"),
    ("availability", r"(?<!не )(?:есть в наличии|в наличии есть|имеется на складе|есть на складе)"),
    ("availability", r"(?:нет|не имеется|отсутству\w*)\s+(?:\w+\s+){0,2}(?:остат\w*|в наличии|на складе)|остат\w*\s+(?:\w+\s+){0,4}(?:нет|отсутству\w*)|нет в наличии"),
    ("compatibility", r"(?<!не )(?:точно подойд|гарантированно|гарантируем|полностью совместим)"),
    ("payment", r"(?<!не )(?:можно оплатить на сайте|оплата на сайте доступна|принимаем оплату на сайте)"),
]


@dataclass
class VerificationResult:
    status: str  # supported | unsupported
    unsupported: list[str] = field(default_factory=list)


def _numbers(text: str) -> list[Decimal]:
    values = []
    for match in _NUMBER.finditer(text.replace(" ", " ")):
        raw = re.sub(r"[  ]", "", match.group()).replace(",", ".")
        try:
            values.append(Decimal(raw))
        except InvalidOperation:
            continue
    return values


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= Decimal("0.005")


def verify_answer(answer: str, facts: FactSet, user_text: str = "", *, remnant_checked: bool = False) -> VerificationResult:
    # C3-F5: membership in a numeric whitelist does not establish a commercial
    # assertion. Only complete domain-rendered claims can carry money or stock.
    # Check the surrounding model prose BEFORE expanding references. An attacker
    # cannot use a real amount with a different product, role, unit or quantity.
    remainder = answer
    for key, claim in facts.commercial_claims.items():
        remainder = remainder.replace(f"[[{key}]]", "").replace(claim, "")
    allowed = {value for value in facts.numbers()} | set(_numbers(user_text))
    # Literal small counts in fixed phrases ("4 сторонам", "2–4") are not commercial claims.
    allowed |= {Decimal(n) for n in range(0, 13)}
    unsupported: list[str] = []
    if re.search(r"\[\[|₸|тенге|\bтг\b|tg/|\b(?:цена|стоимость|итого|стоит|ставка)\b.{0,60}\d", remainder, re.I):
        unsupported.append("claim:unbound_commercial")
    shown = _numbers(facts.render(answer))
    for value in shown:
        if not any(abs(value - known) <= Decimal("0.005") for known in allowed):
            unsupported.append(f"number:{value}")
    for quote in facts.quotes:
        names_line = any(_close(value, line) for value in shown for line in quote.lines)
        if names_line and not any(_close(value, quote.total) for value in shown):
            unsupported.append(f"claim:incomplete_total:{quote.total}")
    lowered = remainder.lower().replace("ё", "е")
    for kind, pattern in _CLAIMS:
        if re.search(pattern, lowered):
            unsupported.append(f"claim:{kind}")
    return VerificationResult("unsupported" if unsupported else "supported", sorted(set(unsupported)))
