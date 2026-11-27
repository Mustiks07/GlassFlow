"""The single exact pricing service used by HTTP quotes, AI tools, dialog checks and exports.

Rules (TZ §14):
- money is Decimal parsed from strings; area = length_mm × width_mm / 1 000 000 m²;
  edge length = confirmed sides in mm / 1000 m; quantity is a positive integer;
- glass and processing are multiplied by quantity; each displayed line is rounded
  ROUND_HALF_UP to 0.01 and the total is the sum of the displayed lines;
- sheet price and per-m² rate are independent; a missing rate is never derived from a sheet;
- hardware uses retail below the KB threshold and the bulk price from it; unknown quantity
  shows both tiers; null prices stay unknown;
- edge rates only from the KB rule; other thicknesses, facet and sandblast go to the manager.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from glassflow.contracts.common import Evidence

from .catalog.kb import KnowledgeBase, PriceEntry, Product

CENT = Decimal("0.01")
MM2_PER_M2 = Decimal(1_000_000)
MM_PER_M = Decimal(1000)
ROUNDING_POLICY = "ROUND_HALF_UP to 0.01 per line; total equals the sum of displayed lines"
SIDE_NAMES_RU = {"top": "верх", "bottom": "низ", "left": "левая", "right": "правая"}


def resolve_sides(selected: tuple[str, ...], length_mm: int | None, width_mm: int | None) -> tuple[str, ...]:
    """Map «длинные/короткие стороны» to the real sides; top/bottom run along length_mm."""
    if selected in {("long",), ("short",)} and length_mm is not None and width_mm is not None:
        length_is_long = length_mm >= width_mm
        want_long = selected == ("long",)
        return ("top", "bottom") if length_is_long == want_long else ("left", "right")
    return tuple(side for side in selected if side in {"top", "bottom", "left", "right"})


def pricing_input_for(
    product,
    *,
    length_mm: int | None,
    width_mm: int | None,
    quantity: int | None,
    processing: str = "none",
    edge_sides: str | None = None,
    selected_sides: tuple[str, ...] = (),
    price_basis: str = "per_m2",
    thickness_mm: int | None = None,
) -> tuple["PricingInput", bool]:
    """The ONE normalization of request parameters into PricingInput (assistant, tools, dialog checks).

    Returns ``(input, edge_sides_unknown)``. Edge sides must be stated explicitly: «все стороны» →
    all; «длинные/короткие» are resolved against the real sizes; named sides as given. When edge
    processing is requested without identifiable sides, the input carries ``selected`` with no sides
    so Pricing reports ``edge_sides_unknown`` instead of assuming all four.
    """
    sides = resolve_sides(tuple(selected_sides), length_mm, width_mm)
    unknown = processing == "euro_edge" and (edge_sides is None or (edge_sides == "selected" and not sides))
    mode = "all" if processing == "euro_edge" and edge_sides == "all" else "selected"
    if processing != "euro_edge":
        mode, sides = "all", ()
    return (
        PricingInput(product, length_mm, width_mm, quantity, processing, mode, sides if mode == "selected" else (), price_basis, thickness_mm),
        unknown,
    )


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def money_str(value: Decimal | None) -> str | None:
    return None if value is None else f"{money(value):f}"


@dataclass(frozen=True)
class PricingInput:
    product: Product
    length_mm: int | None = None
    width_mm: int | None = None
    quantity: int | None = 1
    processing_kind: str = "none"  # none | euro_edge | facet | sandblast
    sides: str = "all"  # all | selected
    selected_sides: tuple[str, ...] = ()
    price_basis: str = "auto"  # auto | per_m2 | per_sheet | unit
    thickness_mm: int | None = None  # confirmed thickness; defaults to the product attribute


@dataclass
class PricedLine:
    component: str
    label: str
    quantity: int
    unit_price: Decimal
    unit: str
    measure_per_unit: Decimal | None
    exact: Decimal
    amount: Decimal
    formula: str
    evidence: list[Evidence]


@dataclass
class Unknown:
    component: str
    reason_code: str
    message_ru: str
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class TierPrice:
    price_type: str
    amount: Decimal | None
    minimum_quantity: int | None
    evidence: Evidence


@dataclass
class PricingResult:
    product: Product
    kb_version: str
    lines: list[PricedLine]
    unknowns: list[Unknown]
    total: Decimal | None
    known_subtotal: Decimal | None
    price_basis: str
    confirmed_parameters: dict[str, str]
    assumptions: list[str]
    tiers: list[TierPrice]
    clarification: str | None

    @property
    def complete(self) -> bool:
        return not self.unknowns and bool(self.lines)


class PricingInputError(ValueError):
    def __init__(self, field_name: str, message_ru: str):
        super().__init__(message_ru)
        self.field_name = field_name
        self.message_ru = message_ru


def _evidence(kb: KnowledgeBase, record_id: str, field_name: str | None) -> Evidence:
    return Evidence(source=kb.source, source_version=kb.version, record_id=record_id, field=field_name)


def _known(entry: PriceEntry | None) -> bool:
    return entry is not None and entry.amount is not None


def _exact_str(value: Decimal) -> str:
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def calculate(kb: KnowledgeBase, request: PricingInput) -> PricingResult:
    product = request.product
    if kb.product(product.product_id) != product:
        raise PricingInputError("catalog_product_id", "Товар не принадлежит указанной версии KB.")
    quantity = request.quantity
    if quantity is not None and (isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0):
        raise PricingInputError("quantity", "Количество должно быть положительным целым числом.")
    for name, value in (("length_mm", request.length_mm), ("width_mm", request.width_mm)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value <= 0):
            raise PricingInputError(name, "Размер должен быть положительным целым числом миллиметров.")
    if (request.length_mm is None) != (request.width_mm is None):
        raise PricingInputError("dimensions", "Нужны обе стороны детали: длина и ширина.")
    if request.processing_kind not in {"none", "euro_edge", "facet", "sandblast"}:
        raise PricingInputError("processing.kind", "Неизвестный вид обработки.")
    if request.price_basis not in {"auto", "per_m2", "per_sheet", "unit"}:
        raise PricingInputError("price_basis", "Неизвестная база цены.")

    if product.is_hardware:
        return _hardware(kb, request)
    return _material(kb, request)


def _base_params(request: PricingInput) -> dict[str, str]:
    params = {"catalog_product_id": request.product.product_id, "product_name": request.product.name}
    if request.length_mm is not None:
        params["length_mm"] = str(request.length_mm)
        params["width_mm"] = str(request.width_mm)
    if request.quantity is not None:
        params["quantity"] = str(request.quantity)
    return params


def _hardware(kb: KnowledgeBase, request: PricingInput) -> PricingResult:
    product = request.product
    retail = product.price("retail_unit")
    bulk = product.price("bulk_unit")
    tiers = [
        TierPrice(entry.price_type, entry.amount, entry.minimum_quantity, _evidence(kb, product.product_id, entry.source_field))
        for entry in (retail, bulk)
        if entry is not None
    ]
    lines: list[PricedLine] = []
    unknowns: list[Unknown] = []
    assumptions: list[str] = []
    params = _base_params(request)
    params.pop("length_mm", None)
    params.pop("width_mm", None)
    clarification = None
    if request.length_mm is not None:
        assumptions.append("Размеры не применяются к штучной фурнитуре.")
    if request.price_basis in {"per_m2", "per_sheet"}:
        unknowns.append(Unknown("unit_price", "basis_not_applicable", "Для фурнитуры цена указана за штуку."))
    threshold = bulk.minimum_quantity if bulk is not None else None
    if request.quantity is None:
        clarification = "Уточните количество штук: цена зависит от порога заказа."
        unknowns.append(Unknown("quantity", "quantity_unknown", clarification))
    else:
        use_bulk = threshold is not None and request.quantity >= threshold
        entry = bulk if use_bulk else retail
        if _known(entry):
            assert entry is not None and entry.amount is not None
            exact = entry.amount * request.quantity
            tier_ru = f"от {threshold} шт" if use_bulk else "розница"
            lines.append(
                PricedLine(
                    "hardware",
                    f"{product.name} ({tier_ru})",
                    request.quantity,
                    entry.amount,
                    "шт",
                    Decimal(1),
                    exact,
                    money(exact),
                    f"{request.quantity} шт × {_exact_str(entry.amount)} ₸",
                    [_evidence(kb, product.product_id, entry.source_field)],
                )
            )
        else:
            tier_ru = f"от {threshold} штук" if use_bulk else "в розницу"
            unknowns.append(
                Unknown(
                    "hardware",
                    "price_not_in_kb",
                    f"Цены «{product.name}» {tier_ru} в базе нет; её назовет менеджер.",
                    [_evidence(kb, product.product_id, entry.source_field if entry else None)],
                )
            )
    return _finish(kb, request, lines, unknowns, params, assumptions, tiers, clarification, "unit")


def _material(kb: KnowledgeBase, request: PricingInput) -> PricingResult:
    product = request.product
    per_m2 = product.price("per_m2")
    sheet = product.price("per_sheet")
    lines: list[PricedLine] = []
    unknowns: list[Unknown] = []
    assumptions: list[str] = []
    params = _base_params(request)
    clarification = None
    has_dims = request.length_mm is not None
    basis = request.price_basis
    if basis == "auto":
        basis = "per_m2" if has_dims or not _known(sheet) else "per_sheet"
    if basis == "unit":
        unknowns.append(Unknown("glass", "basis_not_applicable", "Стекло и зеркала считаются по м² или листу."))
        basis = "per_m2"

    if basis == "per_sheet":
        params["price_basis"] = "per_sheet"
        if not _known(sheet):
            unknowns.append(
                Unknown(
                    "sheet",
                    "sheet_price_not_in_kb",
                    f"Цены целого листа «{product.name}» в базе нет; её назовет менеджер.",
                    [_evidence(kb, product.product_id, sheet.source_field if sheet else None)],
                )
            )
        elif request.quantity is None:
            clarification = "Уточните количество листов."
            unknowns.append(Unknown("quantity", "quantity_unknown", clarification))
        else:
            assert sheet is not None and sheet.amount is not None
            exact = sheet.amount * request.quantity
            lines.append(
                PricedLine(
                    "sheet",
                    f"{product.name}, целый лист",
                    request.quantity,
                    sheet.amount,
                    "лист",
                    Decimal(1),
                    exact,
                    money(exact),
                    f"{request.quantity} лист × {_exact_str(sheet.amount)} ₸",
                    [_evidence(kb, product.product_id, sheet.source_field)],
                )
            )
        if has_dims:
            assumptions.append("Цена целого листа не зависит от размеров детали.")
    else:
        params["price_basis"] = "per_m2"
        if not has_dims:
            clarification = "Укажите размеры детали в мм (длина × ширина)."
            unknowns.append(Unknown("dimensions", "dimensions_unknown", clarification))
        elif request.quantity is None:
            clarification = "Уточните количество деталей."
            unknowns.append(Unknown("quantity", "quantity_unknown", clarification))
        elif not _known(per_m2):
            sheet_note = ""
            if _known(sheet):
                assert sheet is not None and sheet.amount is not None
                sheet_note = " Известна только цена целого листа; ставку за м² из нее не выводим."
            unknowns.append(
                Unknown(
                    "glass",
                    "per_m2_price_not_in_kb",
                    f"Ставки за м² для «{product.name}» в базе нет.{sheet_note} Стоимость детали рассчитает менеджер.",
                    [_evidence(kb, product.product_id, per_m2.source_field if per_m2 else "цена_за_м2_тг")],
                )
            )
        else:
            assert per_m2 is not None and per_m2.amount is not None
            area = Decimal(request.length_mm) * Decimal(request.width_mm) / MM2_PER_M2
            exact = area * per_m2.amount * request.quantity
            lines.append(
                PricedLine(
                    "glass",
                    f"{product.name} {request.length_mm}×{request.width_mm} мм",
                    request.quantity,
                    per_m2.amount,
                    "м²",
                    area,
                    exact,
                    money(exact),
                    f"{_exact_str(area)} м² × {_exact_str(per_m2.amount)} ₸/м² × {request.quantity} шт",
                    [_evidence(kb, product.product_id, per_m2.source_field)],
                )
            )

    _processing(kb, request, lines, unknowns, params, assumptions)
    return _finish(kb, request, lines, unknowns, params, assumptions, [], clarification, params["price_basis"])


def _processing(kb, request, lines, unknowns, params, assumptions) -> None:
    kind = request.processing_kind
    if kind == "none":
        return
    params["processing"] = kind
    product = request.product
    if kind in {"facet", "sandblast"}:
        name = "фацета" if kind == "facet" else "пескоструйной обработки"
        rule = kb.rules_for("facet")[0].rule_id if kind == "facet" and kb.rules_for("facet") else None
        unknowns.append(
            Unknown(
                kind,
                "processing_price_not_in_kb",
                f"Цены {name} в базе нет; её назовет менеджер.",
                [_evidence(kb, rule, "правило")] if rule else [],
            )
        )
        return
    # euro edge
    thickness = request.thickness_mm if request.thickness_mm is not None else product.thickness_mm
    if request.length_mm is None or request.quantity is None:
        unknowns.append(Unknown("edge", "dimensions_unknown", "Для расчета кромки нужны размеры и количество."))
        return
    if request.sides == "all":
        edge_mm = 2 * (request.length_mm + request.width_mm)
        sides_ru = "все 4 стороны"
        params["edge_sides"] = "all"
    else:
        chosen = list(dict.fromkeys(request.selected_sides))
        if not chosen or any(side not in SIDE_NAMES_RU for side in chosen):
            unknowns.append(
                Unknown("edge", "edge_sides_unknown", "Уточните, какие стороны обрабатывать кромкой.")
            )
            return
        edge_mm = sum(request.length_mm if side in {"top", "bottom"} else request.width_mm for side in chosen)
        sides_ru = ", ".join(SIDE_NAMES_RU[side] for side in chosen)
        params["edge_sides"] = ",".join(chosen)
    if thickness is None:
        unknowns.append(
            Unknown("edge", "thickness_unknown", "Уточните толщину стекла: ставка кромки зависит от толщины.")
        )
        return
    rate = kb.edge_rate(thickness)
    if rate is None:
        unknowns.append(
            Unknown(
                "edge",
                "edge_rate_not_in_kb",
                f"Ставки евро-кромки для {thickness} мм в базе нет; цену назовет менеджер.",
                [_evidence(kb, kb.edge_rule_id, "правило")] if kb.edge_rule_id else [],
            )
        )
        return
    length_m = Decimal(edge_mm) / MM_PER_M
    exact = length_m * rate.amount_per_m * request.quantity
    lines.append(
        PricedLine(
            "edge",
            f"Евро-кромка {thickness} мм ({sides_ru})",
            request.quantity,
            rate.amount_per_m,
            "м",
            length_m,
            exact,
            money(exact),
            f"{_exact_str(length_m)} м × {_exact_str(rate.amount_per_m)} ₸/м × {request.quantity} шт",
            [_evidence(kb, rate.rule_id, "правило")],
        )
    )


def _finish(kb, request, lines, unknowns, params, assumptions, tiers, clarification, basis) -> PricingResult:
    subtotal = sum((line.amount for line in lines), Decimal(0)) if lines else None
    total = subtotal if lines and not unknowns else None
    if clarification is None and unknowns:
        clarification = unknowns[0].message_ru
    return PricingResult(
        product=request.product,
        kb_version=kb.version,
        lines=lines,
        unknowns=unknowns,
        total=total,
        known_subtotal=subtotal,
        price_basis=basis,
        confirmed_parameters=params,
        assumptions=assumptions,
        tiers=tiers,
        clarification=clarification,
    )
