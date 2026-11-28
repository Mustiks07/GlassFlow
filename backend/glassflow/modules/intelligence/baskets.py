"""Conservative multi-line parsing. Every source fragment survives as a line."""

import json
import re

from glassflow.contracts.baskets import BasketLineDraft, BasketParseResult
from glassflow.contracts.common import Dimensions
from glassflow.contracts.intelligence import QuoteRequest
from glassflow.modules.intelligence.assistant.local import LocalEngine, TurnContext
from glassflow.modules.intelligence.catalog.kb import parse_knowledge_base
from glassflow.modules.intelligence.service import _processing_from


def parse_basket(snapshot, context):
    kb = parse_knowledge_base(json.dumps(snapshot["kb"], ensure_ascii=False).encode("utf-8"))
    engine = LocalEngine(kb, {}, dataset_id=snapshot["dataset_id"])
    fragments = [p.strip() for p in re.split(r"[;\n]+", snapshot["request_text"]) if p.strip()]
    lines, warnings = [], []
    for index, fragment in enumerate(fragments or [snapshot["request_text"]]):
        context.progress("parsing", index, len(fragments) or 1)
        out = engine.respond(fragment, TurnContext(customer_id=snapshot["customer_ref"]), inventory_mode="none")
        request, clarification = None, out.clarification
        if out.pricing and out.pricing.product:
            pricing = out.pricing
            confirmed = pricing.confirmed_parameters
            request = QuoteRequest(dataset_id=snapshot["dataset_id"], catalog_product_id=pricing.product.product_id,
                kb_version=kb.version, customer_id=snapshot["customer_ref"],
                dimensions=Dimensions(length_mm=int(confirmed["length_mm"]), width_mm=int(confirmed["width_mm"]))
                    if "length_mm" in confirmed else None,
                quantity=int(confirmed["quantity"]) if "quantity" in confirmed else None,
                processing=_processing_from(pricing), price_basis=pricing.price_basis,
                assumptions=out.assumptions)
        if request is None or out.missing_parameters or out.needs_manager:
            clarification = clarification or "Уточните товар, размеры, количество и обработку этой строки."
        if out.context.quantity_assumed:
            clarification = "Подтвердите количество этой позиции; в предварительном расчете принято 1."
        # Multiple dimensions in one fragment are never silently collapsed.
        from glassflow.modules.intelligence.nlu.extract import extract
        if len(extract(fragment).dimensions) > 1:
            request, clarification = None, "Разделите позиции с разными размерами точкой с запятой или новой строкой."
        lines.append(BasketLineDraft(line_id=f"line-{index + 1}", text=fragment, request=request, clarification=clarification))
    return BasketParseResult(dataset_id=snapshot["dataset_id"], basket_id=snapshot["basket_id"],
        basket_version=snapshot["basket_version"], input_hash=snapshot["input_hash"], lines=lines, warnings=warnings).model_dump(mode="json")
