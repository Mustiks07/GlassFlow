"""Knowledge base parsing.

The KB JSON is data. Product names, prices, nulls and rule texts are preserved verbatim; fields
that this parser does not understand are kept in ``unknown_fields`` as data and never executed
or turned into instructions. Rule texts are scanned only for explicit, auditable facts (edge
rates, AB model range) with a ``source_ref``; if the pattern is absent the fact is unknown.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from .text import normalize

KNOWN_PRICE_FIELDS = {
    "цена_за_м2_тг": ("per_m2", "м²"),
    "цена_листа_тг": ("per_sheet", "лист"),
    "цена_розница_тг": ("retail_unit", "шт"),
}
_BULK_FIELD = re.compile(r"^цена_от_(\d+)_шт_тг$")
_STRUCTURAL_FIELDS = {"id", "название", "вид"}


class KnowledgeBaseError(ValueError):
    """The KB bytes cannot be used as a catalog source."""


@dataclass(frozen=True)
class PriceEntry:
    price_type: str  # per_m2 | per_sheet | retail_unit | bulk_unit
    amount: Decimal | None
    unit: str
    source_field: str
    minimum_quantity: int | None = None


@dataclass(frozen=True)
class Product:
    product_id: str
    name: str
    kind: str
    prices: tuple[PriceEntry, ...]
    attributes: dict[str, str]
    unknown_fields: dict[str, str]
    position: int

    def price(self, price_type: str) -> PriceEntry | None:
        for entry in self.prices:
            if entry.price_type == price_type:
                return entry
        return None

    @property
    def thickness_mm(self) -> int | None:
        value = self.attributes.get("thickness_mm")
        return int(value) if value else None

    @property
    def is_hardware(self) -> bool:
        return self.kind == "hardware"


@dataclass(frozen=True)
class Rule:
    rule_id: str
    text: str
    topics: tuple[str, ...]


@dataclass(frozen=True)
class EdgeRate:
    thickness_mm: int
    amount_per_m: Decimal
    rule_id: str


@dataclass(frozen=True)
class KnowledgeBase:
    version: str
    sha256: str
    source: str
    products: tuple[Product, ...]
    rules: tuple[Rule, ...]
    edge_rates: tuple[EdgeRate, ...]
    edge_rule_id: str | None
    model_range: tuple[str, int, int, str] | None  # prefix, first, last, rule_id
    missing_models: tuple[tuple[str, str], ...]  # (code, rule_id)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def product(self, product_id: str) -> Product | None:
        return self._index.get(product_id)

    @property
    def _index(self) -> dict[str, Product]:
        cached = self.__dict__.get("_cached_index")
        if cached is None:
            cached = {product.product_id: product for product in self.products}
            object.__setattr__(self, "_cached_index", cached)
        return cached

    def rules_for(self, topic: str) -> list[Rule]:
        return [rule for rule in self.rules if topic in rule.topics]

    def edge_rate(self, thickness_mm: int | None) -> EdgeRate | None:
        if thickness_mm is None:
            return None
        for rate in self.edge_rates:
            if rate.thickness_mm == thickness_mm:
                return rate
        return None


def kb_version_for(content: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(content).hexdigest()
    return f"kb-{digest[:16]}", digest


def _decimal(value: object, field_name: str, product_id: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise KnowledgeBaseError(f"{product_id}.{field_name}: булево значение вместо цены")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise KnowledgeBaseError(f"{product_id}.{field_name}: нечисловая цена {value!r}") from exc
    if amount < 0 or not amount.is_finite():
        raise KnowledgeBaseError(f"{product_id}.{field_name}: недопустимая цена {value!r}")
    return amount


_FAMILY_PATTERNS = [
    ("tempered", r"\bкален"),
    ("patterned", r"\bрифлен"),
    ("mirror", r"\bзеркал"),
    ("lacobel", r"\bлакобел"),
    ("matelux", r"\bмателюкс"),
    ("checkered", r"\bквадратик"),
    ("reflective", r"\bотражающ"),
]
_COLOR_PATTERNS = [
    ("прозрачное", r"\bпрозрачн"),
    ("серое", r"\bсер(ое|ого|ый|ая|ое)?\b"),
    ("бронза", r"\bбронз"),
    ("green", r"\bgreen\b"),
    ("золото", r"\bзолот"),
    ("чёрный/белый", r"\bчерн\w* / бел"),
]


def _attributes(name: str, kind: str) -> dict[str, str]:
    text = normalize(name)
    attributes: dict[str, str] = {}
    if kind == "material":
        thickness = re.search(r"(?<![\dx])(\d{1,2})\s*мм\b", text)
        if thickness:
            attributes["thickness_mm"] = thickness.group(1)
        sheet = re.search(r"лист\s+(\d{3,5})\s*x\s*(\d{3,5})", text)
        if sheet:
            attributes["sheet_format_mm"] = f"{sheet.group(1)}x{sheet.group(2)}"
        families = [label for label, pattern in _FAMILY_PATTERNS if re.search(pattern, text)]
        if families:
            attributes["families"] = ",".join(families)
        colors = [label for label, pattern in _COLOR_PATTERNS if re.search(pattern, text)]
        if colors:
            attributes["color"] = ",".join(colors)
        if "комфорт" in text:
            attributes["variant"] = "комфорт"
    return attributes


_TOPIC_PATTERNS = [
    ("installation", r"монтаж|установ"),
    ("payment", r"оплат|kaspi|карт"),
    ("delivery", r"доставк"),
    ("discount", r"скидк|акци"),
    ("pricing_source", r"прайс|если позиции или цены в базе нет"),
    ("edge_processing", r"кромк"),
    ("facet", r"фацет"),
    ("mirror_formats", r"зеркало\s+\d+\s*мм\s+прода"),
    ("mirror_models", r"\bab\d{3,5}"),
    ("manager_handoff", r"менеджер"),
]


def _rule_topics(text: str) -> tuple[str, ...]:
    low = normalize(text)
    return tuple(topic for topic, pattern in _TOPIC_PATTERNS if re.search(pattern, low))


_EDGE_RATE = re.compile(r"(\d{1,2})\s*мм\s*-\s*(\d[\d ]*)\s*(?:₸|тг|тенге)\s*за\s*метр")
_MODEL_RANGE = re.compile(r"\b([a-z]{1,4})(\d{3,5})\s*-\s*\1(\d{3,5})\b")
_MISSING_MODEL = re.compile(r"модел\w*\s+([a-z]{1,4}\d{3,5})\s+в\s+каталоге\s+нет")


def parse_knowledge_base(content: bytes, source: str = "ksm_knowledge_base.json") -> KnowledgeBase:
    version, digest = kb_version_for(content)
    try:
        document = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KnowledgeBaseError(f"KB не является корректным UTF-8 JSON: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("товары"), list):
        raise KnowledgeBaseError("KB не содержит списка 'товары'")
    raw_rules = document.get("правила", [])
    if not isinstance(raw_rules, list):
        raise KnowledgeBaseError("Поле 'правила' должно быть списком")

    warnings: list[str] = []
    products: list[Product] = []
    seen: set[str] = set()
    for position, item in enumerate(document["товары"]):
        if not isinstance(item, dict):
            raise KnowledgeBaseError(f"товар #{position}: ожидается объект")
        product_id = item.get("id")
        name = item.get("название")
        kind = item.get("вид")
        if not isinstance(product_id, str) or not product_id.strip():
            raise KnowledgeBaseError(f"товар #{position}: нет id")
        if product_id in seen:
            raise KnowledgeBaseError(f"товар {product_id}: повторяющийся id")
        seen.add(product_id)
        if not isinstance(name, str) or not name.strip():
            raise KnowledgeBaseError(f"товар {product_id}: нет названия")
        kind = kind if isinstance(kind, str) else "unknown"
        prices: list[PriceEntry] = []
        unknown: dict[str, str] = {}
        for key, value in item.items():
            if key in _STRUCTURAL_FIELDS:
                continue
            if key in KNOWN_PRICE_FIELDS:
                price_type, unit = KNOWN_PRICE_FIELDS[key]
                prices.append(PriceEntry(price_type, _decimal(value, key, product_id), unit, key))
                continue
            bulk = _BULK_FIELD.match(key)
            if bulk:
                prices.append(
                    PriceEntry("bulk_unit", _decimal(value, key, product_id), "шт", key, int(bulk.group(1)))
                )
                continue
            unknown[key] = json.dumps(value, ensure_ascii=False)
        if unknown:
            warnings.append(f"{product_id}: неизвестные поля сохранены как данные: {sorted(unknown)}")
        products.append(
            Product(product_id, name, kind, tuple(prices), _attributes(name, kind), unknown, position)
        )

    rules: list[Rule] = []
    edge_rates: list[EdgeRate] = []
    edge_rule_id: str | None = None
    model_range = None
    missing_models: list[tuple[str, str]] = []
    for position, item in enumerate(raw_rules):
        if not isinstance(item, dict) or not isinstance(item.get("правило"), str):
            raise KnowledgeBaseError(f"правило #{position}: ожидается объект с текстом")
        rule_id = str(item.get("id") or f"rule-{position + 1}")
        text = item["правило"]
        rules.append(Rule(rule_id, text, _rule_topics(text)))
        low = normalize(text)
        if "кромк" in low:
            for thickness, amount in _EDGE_RATE.findall(low):
                edge_rates.append(EdgeRate(int(thickness), Decimal(amount.replace(" ", "")), rule_id))
                edge_rule_id = rule_id
        range_match = _MODEL_RANGE.search(low)
        if range_match:
            model_range = (range_match.group(1), int(range_match.group(2)), int(range_match.group(3)), rule_id)
        for code in _MISSING_MODEL.findall(low):
            missing_models.append((code, rule_id))

    return KnowledgeBase(
        version=version,
        sha256=digest,
        source=source,
        products=tuple(products),
        rules=tuple(rules),
        edge_rates=tuple(edge_rates),
        edge_rule_id=edge_rule_id,
        model_range=model_range,
        missing_models=tuple(missing_models),
        warnings=tuple(warnings),
    )
