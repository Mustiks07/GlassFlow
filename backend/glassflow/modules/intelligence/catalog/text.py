"""Text normalization helpers shared by catalog matching, NLU and dialog checks.

Pure functions, no I/O. Source strings are never modified in storage; these helpers only
produce comparison keys.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

_DIM_SEP = re.compile(r"(?<=\d)\s*[x×х\*]\s*(?=\d)", re.IGNORECASE)
_SPACES = re.compile(r"\s+")
_WORD = re.compile(r"[a-zа-я0-9]+(?:-[a-zа-я0-9]+)*", re.IGNORECASE)

# Russian adjective/noun endings, longest first. Stem keeps at least three letters.
_ENDINGS = sorted(
    [
        "ыми", "ими", "ого", "его", "ому", "ему", "ая", "яя", "ое", "ее", "ые", "ие", "ый", "ий", "ой",
        "ую", "юю", "ых", "их", "ом", "ем", "ам", "ям", "ах", "ях", "ами", "ями", "ов", "ев",
        "ия", "ию", "ей", "иями",
        "а", "я", "о", "е", "ы", "и", "у", "ю", "ь",
    ],
    key=len,
    reverse=True,
)

# Spelling variants that denote the same attribute. Values are canonical stems.
_SYNONYM_STEMS = {
    "закален": "кален",
    "закаленн": "кален",
    "каленн": "кален",
    "калленн": "кален",
    "каллен": "кален",
    "зеркальн": "зеркал",
    "прозрачк": "прозрачн",
    "бронзов": "бронз",
    "грин": "green",
    "зелен": "green",
}


def normalize(text: str) -> str:
    """Case-fold, replace ё, unify dimension separators and whitespace."""
    value = unicodedata.normalize("NFKC", text).replace(" ", " ").replace(" ", " ")
    value = value.casefold().replace("ё", "е")
    value = value.replace("–", "-").replace("—", "-")
    value = _DIM_SEP.sub("x", value)
    return _SPACES.sub(" ", value).strip()


def words(text: str) -> list[str]:
    return _WORD.findall(normalize(text))


def stem(word: str) -> str:
    """Very small Russian stemmer: strips one ending, maps known spelling variants."""
    token = word.casefold().replace("ё", "е")
    if any(ch.isdigit() for ch in token) or not re.fullmatch(r"[а-я]+", token):
        return token
    for ending in _ENDINGS:
        if token.endswith(ending) and len(token) - len(ending) >= 3:
            token = token[: -len(ending)]
            break
    for variant, canonical in _SYNONYM_STEMS.items():
        if token == variant or (len(variant) >= 5 and token.startswith(variant)):
            return canonical
    return token


def stems_match(a: str, b: str) -> bool:
    if a == b:
        return True
    if min(len(a), len(b)) >= 4 and abs(len(a) - len(b)) <= 3 and (a.startswith(b) or b.startswith(a)):
        return True
    if min(len(a), len(b)) >= 5 and not any(ch.isdigit() for ch in a + b):
        return similarity(a, b) >= 0.8
    return False


def similarity(a: str, b: str) -> float:
    """Optimal-string-alignment (Damerau) ratio in [0, 1]; a swap of two letters costs one edit."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    rows = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        rows[i][0] = i
    for j in range(len(b) + 1):
        rows[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            rows[i][j] = min(rows[i - 1][j] + 1, rows[i][j - 1] + 1, rows[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                rows[i][j] = min(rows[i][j], rows[i - 2][j - 2] + 1)
    return 1.0 - rows[-1][-1] / max(len(a), len(b))


def format_money(value: Decimal) -> str:
    """Russian money rendering: thousands separated by a plain space, decimal comma.

    Whole amounts are rendered without decimals; otherwise exactly two decimals. A plain ASCII
    space is used deliberately: it survives CSV export and every downstream number parser.
    """
    quantized = value.quantize(Decimal("0.01"))
    whole, _, fraction = f"{quantized:f}".partition(".")
    sign = ""
    if whole.startswith("-"):
        sign, whole = "-", whole[1:]
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    text = sign + " ".join(groups)
    if fraction and fraction != "00":
        text += "," + fraction
    return text


def format_decimal(value: Decimal, places: int | None = None) -> str:
    """Render a non-money decimal (area, length) with a decimal comma and no trailing zeros."""
    if places is not None:
        value = value.quantize(Decimal(1).scaleb(-places))
    text = f"{value.normalize():f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")
