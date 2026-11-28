"""Deterministic extraction of request parameters from Russian free text.

The extracted values are *proposals* with their source span; the dialog engine shows the
normalized representation and asks when something is ambiguous. Nothing here reads prices.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from ..catalog.text import normalize

UNIT_FACTORS = {"mm": Decimal(1), "cm": Decimal(10), "m": Decimal(1000)}
_UNIT_WORDS = [
    ("mm", r"мм|миллиметр\w*"),
    ("cm", r"см|сантиметр\w*"),
    ("m", r"м|метр\w*"),
]
_UNIT = r"(?:мм|миллиметр\w*|см|сантиметр\w*|м(?![²2а-я])|метр\w*)"
_NUMBER = r"(?:[+\-−]\s*)?(?:\d{1,3}(?: \d{3})+|\d+)(?:[.,]\d+)?"
_SEP = r"\s*(?:[x×х*]|на)\s*"
_PAIR = re.compile(rf"(?<![\d.,x+\-−])({_NUMBER})\s*({_UNIT})?{_SEP}({_NUMBER})\s*({_UNIT})?(?!\d|[.,]\d|\s*x\s*\d)")
_TRIPLE = re.compile(r"\d+(?:[.,]\d+)?\s*x\s*\d+(?:[.,]\d+)?\s*x\s*\d+(?:[.,]\d+)?")

WORD_NUMBERS = {
    "ноль": 0, "нуль": 0, "полтора": Decimal("1.5"), "полторы": Decimal("1.5"),
    "один": 1, "одна": 1, "одну": 1, "одно": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5,
    "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10, "двадцать": 20, "сто": 100,
}
_COUNT_NOUN = r"(?:шт\b\.?|штук\w*|штуч\w*|детал\w*|лист(?:а|ов)?\b|изделий|изделия|зеркал(?:а|о)?\b|стек(?:ол|ла|ло)|полок)"
_COUNT_NUMBER = r"(?:\(\s*)?(?:[+\-−]\s*)?\d[\d.,/e+\-− ()]*"
_QUANTITY = re.compile(rf"(?:(?<![\w.,/+\-−])|(?<=[a-zа-яё][.,]))({_COUNT_NUMBER})\s*{_COUNT_NOUN}")
_QUANTITY_WORD = re.compile(rf"\b((?:минус\s+)?(?:{'|'.join(WORD_NUMBERS)}))\s+{_COUNT_NOUN}")
_QUANTITY_EXPLICIT = re.compile(rf"(?:в количестве|количеств\w*|кол-?во)\s*[:=]?\s*({_COUNT_NUMBER}|(?:минус\s+)?(?:{'|'.join(WORD_NUMBERS)}))(?![\w])")
_THRESHOLD = re.compile(r"\bот\s+(\d+)\s*(?:шт|штук)|\bопт(?:ом|ов\w*)?\b|оптов")
_THICKNESS = re.compile(r"(?<![\dx.,])(\d{1,2})\s*-?\s*(?:мм|миллиметр\w*)\b")


@dataclass(frozen=True)
class DimensionsProposal:
    length_mm: int
    width_mm: int
    source_text: str
    source_unit: str  # mm | cm | m
    explicit_unit: bool

    @property
    def normalized_text(self) -> str:
        return f"{self.length_mm}×{self.width_mm} мм"


@dataclass
class Extraction:
    text: str
    dimensions: list[DimensionsProposal] = field(default_factory=list)
    ambiguous_dimensions: list[str] = field(default_factory=list)
    invalid_dimensions: list[str] = field(default_factory=list)
    quantity: int | None = None
    quantity_source: str | None = None
    invalid_quantity: str | None = None
    tier_inquiry: bool = False
    thickness_mm: set[int] = field(default_factory=set)
    processing: str = "none"
    edge_sides: str | None = None  # all | selected | None (not stated)
    selected_sides: tuple[str, ...] = ()
    processing_negated: bool = False
    price_basis: str = "auto"
    intents: set[str] = field(default_factory=set)
    model_codes: list[str] = field(default_factory=list)
    unknown_services: list[str] = field(default_factory=list)


def _to_mm(raw: str, unit: str) -> Decimal | None:
    try:
        value = Decimal(raw.replace(" ", "").replace(",", ".").replace("−", "-"))
    except InvalidOperation:
        return None
    return value * UNIT_FACTORS[unit]


def _unit_code(word: str | None) -> str | None:
    if not word:
        return None
    for code, pattern in _UNIT_WORDS:
        if re.fullmatch(pattern, word):
            return code
    return None


def extract_dimensions(text: str, exclude: set[str] | None = None) -> tuple[list[DimensionsProposal], list[str], list[str]]:
    """Return (dimension pairs, ambiguous raw spans, invalid raw spans).

    Pairs equal to ``exclude`` (e.g. a sheet format in a product name, as ``"3210x2250"``)
    are skipped. Explicit cm/m are converted to integer mm; numbers without a unit default to
    mm when they are integers, decimals without a unit are ambiguous.
    """
    # A spaced typographic dash is punctuation; keep it distinct from a signed number.
    value = normalize(re.sub(r"(?<=\s)[—–](?=\s)", " ", text))
    value = re.sub(r"(?<=\d)\s*на\s*(?=\d)", "x", value)
    exclude = exclude or set()
    triples = [m.span() for m in _TRIPLE.finditer(value)]
    found: list[DimensionsProposal] = []
    ambiguous: list[str] = []
    invalid: list[str] = []
    spans: list[tuple[int, int]] = []
    for pattern in (_PAIR,):
        for match in pattern.finditer(value):
            start, end = match.span()
            if any(s <= start < e for s, e in triples) or any(s <= start < e or s < end <= e for s, e in spans):
                continue
            first, unit1, second, unit2 = match.groups()
            if re.search(r"\bминус\s*$", value[:start]):
                invalid.append("минус " + match.group(0).strip())
                spans.append((start, end))
                continue
            key = f"{first.replace(' ', '')}x{second.replace(' ', '')}"
            if key in exclude:
                spans.append((start, end))
                continue
            u1, u2 = _unit_code(unit1), _unit_code(unit2)
            explicit = u1 is not None or u2 is not None
            first_unit, second_unit = u1 or u2 or "mm", u2 or u1 or "mm"
            unit = first_unit if first_unit == second_unit else "mixed"
            if not explicit and ("," in first + second or "." in first + second):
                ambiguous.append(match.group(0).strip())
                spans.append((start, end))
                continue
            a, b = _to_mm(first, first_unit), _to_mm(second, second_unit)
            spans.append((start, end))
            if a is None or b is None or a <= 0 or b <= 0 or a != a.to_integral() or b != b.to_integral():
                invalid.append(match.group(0).strip())
                continue
            found.append(DimensionsProposal(int(a), int(b), match.group(0).strip(), unit, explicit))
    # Explicitly named axes may appear in either order. Each unit belongs to its axis.
    named = list(re.finditer(rf"\b(длина|длиной|ширина|шириной)\s*[:=]?\s*({_NUMBER})\s*({_UNIT})?", value))
    axes = {"length" if m.group(1).startswith("длин") else "width": m for m in named}
    if len(named) == 2 and len(axes) == 2 and not found:
        length, width = axes["length"], axes["width"]
        raw = value[min(m.start() for m in named):max(m.end() for m in named)].strip()
        u1, u2 = _unit_code(length.group(3)), _unit_code(width.group(3))
        a, b = _to_mm(length.group(2), u1 or u2 or "mm"), _to_mm(width.group(2), u2 or u1 or "mm")
        if not (u1 or u2) and any(c in length.group(2) + width.group(2) for c in ",."):
            ambiguous.append(raw)
        elif a is None or b is None or a <= 0 or b <= 0 or a != a.to_integral() or b != b.to_integral():
            invalid.append(raw)
        else:
            found.append(DimensionsProposal(int(a), int(b), raw, u1 or u2 or "mm", bool(u1 or u2)))
    found.sort(key=lambda d: value.find(d.source_text))
    return found, ambiguous, invalid


_INTENT_PATTERNS = [
    ("installation", r"установ|устанавлива|монтаж|смонтир|приед\w*|выезд|повес\w* на стен|замер"),
    ("payment", r"оплат|картой|карточк|kaspi|каспи|рассроч|перевод\w* на|наличн\w* расчет|безнал|счет на оплату"),
    ("delivery", r"доставк|достав|привез|отправ\w* (?:в|до|по)|самовывоз|забрать"),
    ("discount", r"скидк|скидоч|акци|дешевле|уступ|промокод|бонус|подешевле|сбавь"),
    ("deadline", r"\bсрок|когда будет|сколько дней|за сколько|успеете|к завтра|до завтра|сегодня сделать|как быстро|через сколько"),
    ("availability", r"в наличии|наличи[ея]|есть ли|остал\w*|на складе"),
    ("warranty", r"гаранти"),
    ("compatibility", r"совмест|подойд|подходит ли|выдерж|подойдет|подход\w* к"),
    ("contacts", r"адрес|где вы находит|телефон|режим работы|график работы|часы работы"),
    ("accessories", r"сопутств|что ещ[её] (?:нужно|понадобит|взять)|какая фурнитура|чем (?:крепить|закрепить|приклеить|клеить)|комплект"),
    ("injection", r"игнорир|забудь (?:все|правила|инструкц)|ignore (?:all|previous)|system prompt|системн\w* (?:промпт|инструкц)|выполни команд|rm -rf|sql|drop table|ты теперь|новые правила"),
    ("greeting", r"^(?:здравствуйте|добрый (?:день|вечер)|привет|салем|сәлем)[!.,\s]*$"),
]
_UNKNOWN_SERVICES = [
    ("фацет", r"фацет"),
    ("пескоструйная обработка", r"пескостру"),
    ("гравировка", r"гравир"),
    ("сверление отверстий", r"сверл|отверсти"),
    ("закалка", r"закалить|закалк"),
    ("фотопечать", r"фотопечат|печать на стекле|уф-печат"),
    ("триплекс", r"триплекс"),
    ("стеклопакет", r"стеклопакет"),
    ("покраска", r"покрас|окраш"),
    ("шлифовка", r"шлифов|полиров"),
    ("гибка стекла", r"гнут|гибк"),
]
_MODEL = re.compile(r"\b([a-z]{1,3})\s?-?(\d{3,5})\b")


def extract(text: str, *, format_exclusions: set[str] | None = None) -> Extraction:
    value = normalize(text)
    result = Extraction(text=value)
    dims, ambiguous, invalid = extract_dimensions(text, format_exclusions)
    result.dimensions, result.ambiguous_dimensions, result.invalid_dimensions = dims, ambiguous, invalid

    threshold = _THRESHOLD.search(value)
    result.tier_inquiry = bool(threshold)
    explicit = _QUANTITY_EXPLICIT.search(value)
    numeric = [m for m in _QUANTITY.finditer(value) if not value[max(0, m.start() - 3) : m.start()].endswith("от ")]
    count = None
    raw_count = None
    if explicit:
        raw_count, result.quantity_source = explicit.group(1), explicit.group(0)
    elif numeric:
        raw_count, result.quantity_source = numeric[0].group(1), numeric[0].group(0)
        if re.search(r"\bминус\s*$", value[:numeric[0].start()]):
            raw_count = "-" + raw_count
            result.quantity_source = "минус " + result.quantity_source
    else:
        word = _QUANTITY_WORD.search(value)
        if word:
            raw_count, result.quantity_source = word.group(1), word.group(0)
    if raw_count is not None:
        count = quantity_value(raw_count)
    if count is not None:
        if count <= 0 or count != count.to_integral():
            result.invalid_quantity = result.quantity_source
        else:
            result.quantity = int(count)

    result.thickness_mm = {int(t) for t in _THICKNESS.findall(re.sub(r"\d+(?:x\d+)+", " ", value))}

    if re.search(r"без (?:обработки|кромки)", value):
        result.processing_negated = True
    elif re.search(r"кромк", value):
        result.processing = "euro_edge"
    if re.search(r"фацет", value):
        result.processing = "facet"
    elif re.search(r"пескостру", value):
        result.processing = "sandblast"
    if re.search(r"(?:по |со )?(?:всем|всех|четыр\w*|4-?м?)\s*сторон|по периметру|по кругу|кругом|вкруговую", value):
        result.edge_sides = "all"
    else:
        sides = _stated_sides(value)
        if sides:
            result.edge_sides, result.selected_sides = "selected", sides
        elif result.processing == "euro_edge" and re.search(r"сторон", value):
            result.edge_sides = "selected"  # sides mentioned but not identifiable

    if re.search(
        r"целого листа|целый лист|за лист\b|листом|цена листа|стоимость листа|лист цел|стоит лист|почем лист|"
        r"\bлист(?:а)? (?:стекла|зеркала)|\bлистами\b|\b(?:\d+|один|два|три|четыре|пять)\s+лист(?:а|ов)?\b",
        value,
    ):
        result.price_basis = "per_sheet"
    if result.quantity_source and re.search(r"\bлист(?:а|ов)?\b", result.quantity_source):
        result.price_basis = "per_sheet"
    elif re.search(r"за (?:квадратн\w* метр|кв\.? ?м|м2|м²|квадрат)|по цене за м|за 1 м|за метр квадратн", value):
        result.price_basis = "per_m2"
    if re.search(r"в розниц|розничн", value) or result.tier_inquiry:
        result.intents.add("tier_prices")

    for intent, pattern in _INTENT_PATTERNS:
        if re.search(pattern, value):
            result.intents.add(intent)
    for label, pattern in _UNKNOWN_SERVICES:
        if re.search(pattern, value):
            result.unknown_services.append(label)
    result.model_codes = [f"{prefix}{number}" for prefix, number in _MODEL.findall(value) if prefix in {"ab"}]
    return result


def quantity_value(raw: str) -> Decimal:
    """Validate the entire numeric span before removing valid thousands separators.

    Unsupported expressions and malformed grouping must not expose a valid
    suffix (``1 / 2`` → ``2``) or become a different integer (``2 3`` → ``23``).
    Zero is the existing invalid-count sentinel, never a default order quantity.
    """
    token = raw.removeprefix("минус ").strip()
    # A sentence/clause terminator is not a decimal digit. All remaining content
    # must still match one number; separators inside expressions are never removed.
    if token.endswith(('.', ',')):
        token = token[:-1]
    if token.startswith('(') and token.endswith(')') and token.count('(') == token.count(')') == 1:
        token = token[1:-1].strip()
    try:
        if token in WORD_NUMBERS:
            value = Decimal(WORD_NUMBERS[token])
        elif re.fullmatch(_NUMBER, token):
            value = Decimal(token.replace(" ", "").replace(",", ".").replace("−", "-"))
        else:
            return Decimal(0)
    except InvalidOperation:
        return Decimal(0)
    return -value if raw.startswith("минус ") else value


_ONE = r"(?:одн(?:ой|у|а)|1)\s+"
_TWO = r"(?:(?:по\s+)?(?:двум|две|двух|обеим|обе|обоих|2)\s+)?"


def _stated_sides(value: str) -> tuple[str, ...]:
    """Edge sides stated in words. ``long``/``short`` = both such sides; ``long1``/``short1`` = one.

    Named sides (верх/низ/лево/право) are returned as is; combinations are concatenated.
    The real sides are resolved against the sizes by ``pricing.resolve_sides``.
    """
    sides: list[str] = []
    if re.search(_ONE + r"длинн\w*", value):
        sides.append("long1")
    elif re.search(_TWO + r"длинн\w*\s+сторон", value):
        sides.append("long")
    if re.search(_ONE + r"(?:\w+\s+)?коротк\w*", value):
        sides.append("short1")
    elif re.search(_TWO + r"коротк\w*\s+сторон", value):
        sides.append("short")
    if re.search(r"сторон|кромк|кром", value):
        for word, side in (("верхн", "top"), ("сверху", "top"), ("нижн", "bottom"), ("снизу", "bottom"),
                           ("лев", "left"), ("слева", "left"), ("прав", "right"), ("справа", "right")):
            if re.search(rf"\b{word}", value) and side not in sides:
                sides.append(side)
    return tuple(sides)


def parse_dimension_text(text: str) -> tuple[str, DimensionsProposal | None, str | None]:
    dims, ambiguous, invalid = extract_dimensions(text)
    if invalid:
        return "invalid", None, f"Размер «{invalid[0]}» не переводится в целые миллиметры."
    if ambiguous or not dims:
        source = ambiguous[0] if ambiguous else text
        return "ambiguous", None, f"Не понятны единицы размера «{source}»: укажите мм, см или м."
    if len(dims) > 1:
        return "ambiguous", None, "Найдено несколько размеров; укажите один размер детали."
    return "ok", dims[0], None
