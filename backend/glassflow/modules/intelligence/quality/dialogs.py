"""Dialog quality control: is the price in the manager's reply correct for the client question?

The check uses the same catalog matcher and Pricing service as the assistant. It interprets
each money value in context (rate per m², sheet, retail, bulk, order total); dimensions,
thickness, model codes, quantities and percentages are not prices. The reference comes from
the KB/Pricing, never from an answer key. Verdicts:

- OK — every recognized price equals the applicable reference (absolute tolerance 0.5 ₸);
- ERROR + correct — a price contradicts a known reference;
- NEEDS_REVIEW — the product/price cannot be determined from the KB (internal state only;
  exports must not turn it into OK/ERROR).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal

from glassflow.contracts.common import Evidence
from glassflow.contracts.intelligence import DialogVerdict, PriceMention

from ..catalog.kb import KnowledgeBase, Product
from ..catalog.matching import match_products
from ..catalog.text import normalize
from ..nlu.extract import extract
from ..pricing import PricingInput, calculate

TOLERANCE = Decimal("0.5")
_MONEY = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:[   ]\d{3})+|\d+)(?:[.,](\d{1,2}))?\s*(?:тг|₸|тенге|тнг|kzt)(?![a-zа-я])",
    re.IGNORECASE,
)
_BARE_NUMBER = re.compile(r"(?<![\w.,x-])(\d{1,3}(?:[   ]\d{3})+|\d{3,})(?:[.,](\d{1,2}))?(?![\w%x]|\s*(?:мм|см|шт|%|x))")


@dataclass
class _Mention:
    amount: Decimal
    raw: str
    meaning: str
    start: int


def money_string(value: Decimal) -> str:
    value = value.quantize(Decimal("0.01"))
    text = f"{value:f}"
    return text[:-3] if text.endswith(".00") else text


def _strip_product_name(text: str, product: Product | None) -> str:
    """Blank out the product name (tolerant to missing commas/brackets) and its sheet format."""
    if product is None:
        return text
    tokens = re.findall(r"[a-zа-я0-9]+", normalize(product.name))
    if tokens:
        pattern = r"[\s,.:;()+\-x×]*".join(re.escape(token) for token in tokens)
        text = re.sub(pattern, lambda m: " " * len(m.group(0)), text, count=1)
    if "sheet_format_mm" in product.attributes:
        text = re.sub(r"лист\w*\s*\d{3,5}\s*x\s*\d{3,5}", lambda m: " " * len(m.group(0)), text)
    return text


def _clause(text: str, start: int, end: int) -> str:
    """The clause around a number: bounded by sentence/clause separators, not decimal commas."""
    left = max(text.rfind(sep, 0, start) for sep in (",", ";", ".", "!", "?", "\n"))
    right_candidates = [text.find(sep, end) for sep in (",", ";", ".", "!", "?", "\n")]
    right = min([pos for pos in right_candidates if pos >= 0], default=len(text))
    return text[left + 1 : right]


def _meaning(clause: str) -> str:
    if re.search(r"(?:/|за|за 1)\s*(?:м2|м²|кв\.?\s?м|квадрат)", clause):
        return "per_m2"
    if re.search(r"от\s+\d+\s*(?:шт|штук)|оптом|при заказе от|оптов", clause):
        return "bulk_unit"
    if re.search(r"в розниц|розничн|за штуку|/\s*шт|за шт\b", clause):
        return "retail_unit"
    if re.search(r"\bлист", clause):
        return "per_sheet"
    if re.search(r"итого|всего|получится|выйдет|общая|за все|стоимость заказа|за \d+ (?:шт|штук|детал)|за детал", clause):
        return "total"
    return "unspecified"


def extract_price_mentions(manager_text: str, product: Product | None) -> list[_Mention]:
    text = _strip_product_name(normalize(manager_text), product)
    mentions: list[_Mention] = []
    for match in _MONEY.finditer(text):
        whole = re.sub(r"[   ]", "", match.group(1))
        amount = Decimal(whole + ("." + match.group(2) if match.group(2) else ""))
        mentions.append(
            _Mention(amount, match.group(0).strip(), _meaning(_clause(text, match.start(), match.end())), match.start())
        )
    if mentions:
        return mentions
    # No currency marker: only numbers that cannot be sizes, thickness, codes, quantities or %.
    cleaned = re.sub(r"\d+(?:[.,]\d+)?\s*x\s*\d+(?:[.,]\d+)?(?:\s*x\s*\d+)?", " ", text)
    for match in _BARE_NUMBER.finditer(cleaned):
        context_before = cleaned[max(0, match.start() - 25) : match.start()]
        if not re.search(r"стоит|цена|стоимост|:|—|-\s*$", context_before):
            continue
        whole = re.sub(r"[   ]", "", match.group(1))
        amount = Decimal(whole + ("." + match.group(2) if match.group(2) else ""))
        mentions.append(
            _Mention(amount, match.group(0).strip(), _meaning(_clause(cleaned, match.start(), match.end())), match.start())
        )
    return mentions


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= TOLERANCE


def _resolve_product(kb: KnowledgeBase, client: str, manager: str) -> tuple[Product | None, str]:
    client_match = match_products(kb, client)
    if client_match.status == "exact":
        return client_match.product, "client_exact"
    manager_match = match_products(kb, manager)
    if client_match.status == "ambiguous" and manager_match.status == "exact":
        ids = {c.product.product_id for c in client_match.candidates}
        if manager_match.product.product_id in ids:
            return manager_match.product, "manager_refined_client_ambiguity"
        return None, "manager_product_outside_client_candidates"
    if client_match.status == "ambiguous":
        amounts = [m.amount for m in extract_price_mentions(manager, None)]
        fitting = []
        for candidate in client_match.candidates:
            refs = _references(kb, candidate.product, client, manager)
            values = [value for value, _ in refs.values() if value is not None]
            if amounts and all(any(_close(amount, value) for value in values) for amount in amounts):
                fitting.append(candidate.product)
        if len(fitting) == 1:
            return fitting[0], "price_matches_unique_client_candidate"
        if amounts and not fitting:
            # No candidate's KB price matches: the price is wrong for every reading of the question
            # (ERROR is certain). The correction comes from the best-ranked candidate and is flagged.
            return client_match.candidates[0].product, "mismatch_all_candidates_best_ranked_correction"
    if client_match.status == "not_found" and manager_match.status == "exact":
        return manager_match.product, "manager_named_product"
    return None, f"client_{client_match.status}"


def _references(kb: KnowledgeBase, product: Product, client: str, manager: str) -> dict[str, tuple[Decimal | None, Evidence]]:
    refs: dict[str, tuple[Decimal | None, Evidence]] = {}

    def ev(field_name: str | None) -> Evidence:
        return Evidence(source=kb.source, source_version=kb.version, record_id=product.product_id, field=field_name)

    for entry in product.prices:
        refs[entry.price_type] = (entry.amount, ev(entry.source_field))
    formats = {product.attributes["sheet_format_mm"]} if "sheet_format_mm" in product.attributes else set()
    ex = extract(client, format_exclusions=formats)
    if ex.dimensions and not product.is_hardware:
        dims = ex.dimensions[0]
        processing = ex.processing if ex.processing == "euro_edge" and ex.edge_sides == "all" else "none"
        result = calculate(
            kb,
            PricingInput(product, dims.length_mm, dims.width_mm, ex.quantity or 1, processing, "all", (), "per_m2"),
        )
        refs["total"] = (result.total, Evidence(source="pricing", source_version=kb.version, record_id=product.product_id, field="total"))
    elif product.is_hardware and ex.quantity:
        result = calculate(kb, PricingInput(product, quantity=ex.quantity, price_basis="unit"))
        refs["total"] = (result.total, Evidence(source="pricing", source_version=kb.version, record_id=product.product_id, field="total"))
    return refs


def check_dialog(kb: KnowledgeBase, dialog_id: str, client: str, manager: str) -> DialogVerdict:
    digest = hashlib.sha256(f"{client}\x1f{manager}".encode("utf-8")).hexdigest()
    if extract(f"{client} {manager}").model_codes:
        product, basis = None, "model_code_question"  # AB models: KB rule decides, not a similar product
    else:
        product, basis = _resolve_product(kb, client, manager)
    mentions = extract_price_mentions(manager, product)
    views = [PriceMention(raw=m.raw, amount_tg=money_string(m.amount), meaning=m.meaning) for m in mentions]
    base = dict(id=dialog_id, mentions=views, input_sha256=digest)
    if product is None:
        codes = extract(f"{client} {manager}").model_codes
        rng = kb.model_range
        missing = {code for code, _ in kb.missing_models}
        if codes and rng and all(
            code.startswith(rng[0]) and rng[1] <= int(re.sub(r"\D", "", code)) <= rng[2] and code not in missing
            for code in codes
        ):
            return DialogVerdict(
                verdict="OK",
                evidence=[Evidence(source=kb.source, source_version=kb.version, record_id=rng[3], field="правило")],
                reason_code="price_set_by_manager_per_kb_rule",
                explanation_ru="По базе цены этих моделей рассчитывает менеджер; противоречия базе нет.",
                **base,
            )
        if not mentions:
            return DialogVerdict(
                verdict="OK", evidence=[], reason_code="no_price_claim",
                explanation_ru="В ответе нет цены, проверять нечего.", **base,
            )
        return DialogVerdict(
            verdict="NEEDS_REVIEW", evidence=[], reason_code=basis,
            explanation_ru="Не удалось однозначно определить товар по базе знаний.", **base,
        )
    refs = _references(kb, product, client, manager)
    ex_client = extract(client)
    bulk_context = ex_client.tier_inquiry or bool(re.search(r"от\s+\d+\s*(?:шт|штук)|оптом", normalize(manager)))
    if not mentions:
        return DialogVerdict(
            verdict="OK", evidence=[], catalog_product_id=product.product_id, reason_code="no_price_claim",
            explanation_ru="Менеджер не назвал цену; ложной цены нет.", **base,
        )
    first_error: tuple[Decimal, str, Evidence] | None = None
    unresolved = False
    evidence: list[Evidence] = []
    for mention in mentions:
        if product.is_hardware:
            order = {
                "retail_unit": ["retail_unit"],
                "bulk_unit": ["bulk_unit"],
                "total": ["total"],
                "unspecified": ["retail_unit"] + (["bulk_unit"] if bulk_context else []) + (["total"] if "total" in refs else []),
            }.get(mention.meaning, ["retail_unit"])
        else:
            if mention.meaning in {"per_m2", "per_sheet", "total"}:
                order = [mention.meaning]
            elif "total" in refs:
                order = ["total", "per_m2"]
            elif ex_client.price_basis == "per_sheet":
                order = ["per_sheet", "per_m2"]
            else:
                order = ["per_m2", "per_sheet"]
        known = [(key, refs[key]) for key in order if key in refs and refs[key][0] is not None]
        if any(_close(mention.amount, value) for _, (value, _) in known):
            key, (value, ref_ev) = next((k, r) for k, r in known if _close(mention.amount, r[0]))
            evidence.append(ref_ev)
            continue
        if known:
            key, (value, ref_ev) = known[0]
            evidence.append(ref_ev)
            if first_error is None:
                first_error = (value, key, ref_ev)
        else:
            unresolved = True
    if first_error is not None:
        value, key, _ = first_error
        ambiguous = basis == "mismatch_all_candidates_best_ranked_correction"
        return DialogVerdict(
            verdict="ERROR",
            correct=money_string(value),
            evidence=evidence,
            catalog_product_id=product.product_id,
            reference_tg=money_string(value),
            reference_meaning=key,
            reason_code="price_mismatch_ambiguous_product" if ambiguous else "price_mismatch",
            explanation_ru=(
                f"Цена не совпадает ни с одной подходящей позицией базы; исправление {money_string(value)} ₸ взято "
                f"у наиболее вероятной позиции «{product.name}» — проверьте товар."
                if ambiguous
                else f"Цена в ответе не совпадает с базой: правильно {money_string(value)} ₸ ({key})."
            ),
            **base,
        )
    if unresolved:
        return DialogVerdict(
            verdict="NEEDS_REVIEW", evidence=evidence, catalog_product_id=product.product_id,
            reason_code="price_not_in_kb",
            explanation_ru="Цены для этого смысла числа нет в базе; проверить может только менеджер.", **base,
        )
    reference = evidence[0] if evidence else None
    primary = None
    for mention in mentions[:1]:
        for key in ("retail_unit", "per_m2", "total", "per_sheet", "bulk_unit"):
            if key in refs and refs[key][0] is not None and _close(mention.amount, refs[key][0]):
                primary = (refs[key][0], key)
                break
    return DialogVerdict(
        verdict="OK",
        evidence=evidence,
        catalog_product_id=product.product_id,
        reference_tg=money_string(primary[0]) if primary else None,
        reference_meaning=primary[1] if primary else (reference.field if reference else None),
        reason_code="price_matches_kb",
        explanation_ru="Цена совпадает с базой знаний.",
        **base,
    )
