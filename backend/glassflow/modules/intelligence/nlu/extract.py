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
_NUMBER = r"\d+(?:[.,]\d+)?"
_GROUPED = r"\d{1,3}(?: \d{3})+"
_SEP = r"\s*(?:x|на)\s*"
_PAIR_GROUPED = re.compile(rf"(?<![\d.,])({_GROUPED})\s*({_UNIT})?{_SEP}({_GROUPED})\s*({_UNIT})?(?!\d|[.,]\d|\s*x\s*\d)")
_PAIR = re.compile(rf"(?<![\d.,x])({_NUMBER})\s*({_UNIT})?{_SEP}({_NUMBER})\s*({_UNIT})?(?!\d|[.,]\d|\s*x\s*\d)")
_TRIPLE = re.compile(r"\d+(?:[.,]\d+)?\s*x\s*\d+(?:[.,]\d+)?\s*x\s*\d+(?:[.,]\d+)?")

WORD_NUMBERS = {
    "один": 1, "одна": 1, "одну": 1, "одно": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5,
    "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10, "двадцать": 20, "сто": 100,
}
_COUNT_NOUN = r"(?:шт\b\.?|штук\w*|штуч\w*|детал\w*|лист(?:а|ов)?\b|изделий|изделия|зеркал(?:а|о)?\b|стекол|полок)"
_QUANTITY = re.compile(rf"(?<!от )(?<!от\s)\b(\d+)\s*{_COUNT_NOUN}")
_QUANTITY_WORD = re.compile(rf"\b({'|'.join(WORD_NUMBERS)})\s+{_COUNT_NOUN}")
_QUANTITY_EXPLICIT = re.compile(r"(?:в количестве|количеств\w*|кол-?во)\s*[:=]?\s*(\d+)")
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
        value = Decimal(raw.replace(" ", "").replace(",", "."))
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
    value = normalize(text)
    value = re.sub(r"(?<=\d)\s*на\s*(?=\d)", "x", value)
    exclude = exclude or set()
    triples = [m.span() for m in _TRIPLE.finditer(value)]
    found: list[DimensionsProposal] = []
    ambiguous: list[str] = []
    invalid: list[str] = []
    spans: list[tuple[int, int]] = []
    for pattern in (_PAIR_GROUPED, _PAIR):
        for match in pattern.finditer(value):
            start, end = match.span()
            if any(s <= start < e for s, e in triples) or any(s <= start < e or s < end <= e for s, e in spans):
                continue
            first, unit1, second, unit2 = match.groups()
            key = f"{first.replace(' ', '')}x{second.replace(' ', '')}"
            if key in exclude:
                spans.append((start, end))
                continue
            unit = _unit_code(unit2) or _unit_code(unit1)
            explicit = unit is not None
            unit = unit or "mm"
            if not explicit and ("," in first + second or "." in first + second):
                ambiguous.append(match.group(0).strip())
                spans.append((start, end))
                continue
            a, b = _to_mm(first, unit), _to_mm(second, unit)
            spans.append((start, end))
            if a is None or b is None or a <= 0 or b <= 0 or a != a.to_integral() or b != b.to_integral():
                invalid.append(match.group(0).strip())
                continue
            found.append(DimensionsProposal(int(a), int(b), match.group(0).strip(), unit, explicit))
    found.sort(key=lambda d: value.find(d.source_text))
    return found, ambiguous, invalid


_INTENT_PATTERNS = [
    ("installation", r"установ|монтаж|смонтир|приед\w*|выезд|повес\w* на стен|замер"),
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
    if explicit:
        result.quantity, result.quantity_source = int(explicit.group(1)), explicit.group(0)
    elif numeric:
        result.quantity, result.quantity_source = int(numeric[0].group(1)), numeric[0].group(0)
    else:
        word = _QUANTITY_WORD.search(value)
        if word:
            result.quantity, result.quantity_source = WORD_NUMBERS[word.group(1)], word.group(0)
    if result.quantity is not None and result.quantity <= 0:
        result.quantity = None

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
        r"\bлист(?:а)? (?:стекла|зеркала)|\bлистами\b",
        value,
    ):
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
