"""Application service of the intelligence module.

One service instance serves HTTP routes, AI tools, batch runs and exports, so every consumer
gets the same Pricing, mappings and verifier. Write transactions are short and never span a
model call: context is read, the AI/turn runs without a transaction, results are written.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import select

from glassflow.contracts.common import Dimensions, Evidence
from glassflow.contracts.cutting import FindRequest
from glassflow.contracts.intelligence import (
    AICheckRequest,
    AICheckResult,
    AIProfileView,
    AnswerBatchRequest,
    AnswerBatchResult,
    AnswerRow,
    AssistantReply,
    AssistantTurn,
    CatalogPrice,
    CatalogProduct,
    CatalogRule,
    CatalogSearchResult,
    Conversation,
    ConversationTurnView,
    DialogBatchRequest,
    DialogBatchResult,
    DialogRequest,
    DialogVerdict,
    DimensionNormalizeResult,
    MappingConfirmRequest,
    MaterialMapping,
    PriceVersion,
    Processing,
    Quote,
    QuoteCancelRequest,
    QuoteConfirmRequest,
    QuoteDiff,
    QuoteLine,
    QuoteLineDiff,
    QuoteRequest,
    QuoteReviseRequest,
    RemnantCandidateRef,
    ToolCallRecord,
    UnknownComponent,
    VerifiedFact,
    WorkingCard,
)

from .assistant.engine import AnswerCache, AssistantEngine
from .assistant.local import TurnContext
from .assistant.prompts import PROMPT_VERSION
from .catalog.kb import KnowledgeBase, KnowledgeBaseError, Product, parse_knowledge_base
from .catalog.mapping import MappingDecision, derive_all
from .catalog.matching import match_products
from .catalog.materials import MaterialsError, MaterialsTable, parse_materials
from .models import AICallRow, ConversationRow, MappingOverrideRow, QualityCheckRow, QuoteRevisionRow, TurnRow
from .nlu.extract import parse_dimension_text
from .ports_consumed import CrmPort, InventoryPort, ScenarioPort, ServiceUnavailable
from .pricing import ROUNDING_POLICY, PricingInput, PricingInputError, PricingResult, calculate, money_str
from .providers.base import ChatMessage, ProviderError, ProviderRequest
from .providers.policy import LedgerEntry
from .providers.settings import AIRuntime
from .quality.dialogs import check_dialog
from .sources import DatasetNotFound, IntelligenceSources, SourceVersionNotFound


class IntelligenceError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message_ru: str,
        *,
        field_errors: list[dict[str, str]] | None = None,
        conflict_objects: list[str] | None = None,
        retryable: bool = False,
    ):
        super().__init__(message_ru)
        self.status = status
        self.code = code
        self.message_ru = message_ru
        self.field_errors = field_errors or []
        self.conflict_objects = conflict_objects or []
        self.retryable = retryable


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class DatasetCatalog:
    dataset_id: str
    kb: KnowledgeBase
    materials: MaterialsTable | None
    origin: str


class DbLedger:
    """Usage ledger in the shared DB: one short write per model attempt, no prompt text."""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    def record(self, entry: LedgerEntry) -> None:
        with self.session_factory.begin() as session:
            session.add(
                AICallRow(
                    id=entry.call_id,
                    created_at=entry.created_at,
                    correlation_id=entry.correlation_id,
                    purpose=entry.purpose,
                    provider=entry.provider,
                    model_id=entry.model_id,
                    attempt=entry.attempt,
                    status=entry.status,
                    error_kind=entry.error_kind,
                    latency_ms=entry.latency_ms,
                    queue_ms=entry.queue_ms,
                    input_tokens=entry.input_tokens,
                    output_tokens=entry.output_tokens,
                    thought_tokens=entry.thought_tokens,
                    cached_tokens=entry.cached_tokens,
                    cost_usd=f"{entry.cost_usd:f}" if entry.cost_usd is not None else None,
                    cost_source=entry.cost_source[:120],
                    prompt_version=entry.prompt_version,
                    cache_hit=False,
                )
            )


class IntelligenceService:
    def __init__(
        self,
        sources: IntelligenceSources,
        session_factory,
        *,
        inventory: InventoryPort | None = None,
        crm: CrmPort | None = None,
        scenario: ScenarioPort | None = None,
        runtime: AIRuntime | None = None,
        clock: Callable[[], str] = utcnow,
    ):
        self.sources = sources
        self.session_factory = session_factory
        self.inventory = inventory
        self.crm = crm
        self.scenario = scenario
        self.runtime = runtime
        self.clock = clock
        self._kb_cache: dict[str, KnowledgeBase] = {}
        self._materials_cache: dict[str, MaterialsTable] = {}
        self._answer_caches: dict[str, AnswerCache] = {}

    # ----------------------------------------------------------------- sources
    def catalog_for(self, dataset_id: str, kb_version: str | None = None) -> DatasetCatalog:
        try:
            document = self.sources.knowledge_base(dataset_id, kb_version)
        except DatasetNotFound:
            raise IntelligenceError(404, "DATASET_NOT_FOUND", f"Набор данных {dataset_id} не найден.") from None
        except SourceVersionNotFound:
            current = self.catalog_for(dataset_id).kb.version
            raise IntelligenceError(
                409, "STALE_KB_VERSION",
                f"Версия базы знаний {kb_version} недоступна; текущая версия {current}.",
                conflict_objects=[current],
            ) from None
        kb = self._kb_cache.get(document.sha256)
        if kb is None:
            try:
                kb = parse_knowledge_base(document.content, document.name)
            except KnowledgeBaseError as exc:
                raise IntelligenceError(422, "KB_INVALID", f"База знаний не принята: {exc}") from None
            self._kb_cache[document.sha256] = kb
        materials = None
        material_doc = self.sources.materials(dataset_id)
        if material_doc is not None:
            materials = self._materials_cache.get(material_doc.sha256)
            if materials is None:
                try:
                    materials = parse_materials(material_doc.content)
                except MaterialsError as exc:
                    raise IntelligenceError(422, "MATERIALS_INVALID", str(exc)) from None
                self._materials_cache[material_doc.sha256] = materials
        return DatasetCatalog(dataset_id, kb, materials, document.origin)

    def _current(self, dataset_id: str, kb_version: str | None) -> DatasetCatalog:
        catalog = self.catalog_for(dataset_id)
        if kb_version and kb_version != catalog.kb.version:
            raise IntelligenceError(
                409, "STALE_KB_VERSION",
                f"Запрос сделан по версии базы знаний {kb_version}, текущая — {catalog.kb.version}. Обновите расчет.",
                conflict_objects=[catalog.kb.version],
            )
        return catalog

    # ----------------------------------------------------------------- mappings
    def effective_mappings(self, catalog: DatasetCatalog) -> dict[str, MappingDecision]:
        if catalog.materials is None:
            derived = {
                p.product_id: MappingDecision(p.product_id, None, "unmapped", "materials_not_imported", (), None, 0)
                for p in catalog.kb.products
            }
        else:
            derived = derive_all(catalog.kb, catalog.materials)
        with self.session_factory() as session:
            rows = session.scalars(
                select(MappingOverrideRow)
                .where(MappingOverrideRow.dataset_id == catalog.dataset_id)
                .order_by(MappingOverrideRow.version)
            ).all()
        for row in rows:
            base = derived.get(row.catalog_product_id)
            if base is None:
                continue
            derived[row.catalog_product_id] = MappingDecision(
                row.catalog_product_id,
                row.material_id,
                row.status,
                row.basis,
                base.candidate_material_ids,
                row.confirmed_by,
                row.version,
            )
        return derived

    def _mapping_dto(self, catalog: DatasetCatalog, decision: MappingDecision) -> MaterialMapping:
        return MaterialMapping(
            dataset_id=catalog.dataset_id,
            catalog_product_id=decision.catalog_product_id,
            material_id=decision.material_id,
            status=decision.status,  # type: ignore[arg-type]
            basis=decision.basis,
            candidate_material_ids=list(decision.candidate_material_ids),
            confirmed_by=decision.confirmed_by,
            version=decision.version,
            kb_version=catalog.kb.version,
            materials_version=catalog.materials.version if catalog.materials else None,
            evidence=[Evidence(source="materials.csv", source_version=catalog.materials.version, record_id=m, field="название")
                      for m in decision.candidate_material_ids] if catalog.materials else [],
        )

    def list_mappings(self, dataset_id: str) -> list[MaterialMapping]:
        catalog = self.catalog_for(dataset_id)
        return [self._mapping_dto(catalog, d) for d in self.effective_mappings(catalog).values()]

    def confirm_mapping(self, product_id: str, request: MappingConfirmRequest) -> MaterialMapping:
        catalog = self.catalog_for(request.dataset_id)
        if catalog.kb.product(product_id) is None:
            raise IntelligenceError(404, "PRODUCT_NOT_FOUND", f"Позиция {product_id} не найдена в этом наборе.")
        current = self.effective_mappings(catalog)[product_id]
        if request.expected_version != current.version:
            raise IntelligenceError(
                409, "VERSION_CONFLICT", "Соответствие уже изменено; обновите данные.", conflict_objects=[f"{product_id}@{current.version}"]
            )
        if request.status == "confirmed":
            if not request.material_id or catalog.materials is None or catalog.materials.get(request.material_id) is None:
                raise IntelligenceError(
                    422, "MATERIAL_NOT_FOUND", "Нужен существующий material_id из materials.csv этого набора.",
                    field_errors=[{"field": "material_id", "message_ru": "material_id не найден"}],
                )
        version = current.version + 1
        with self.session_factory.begin() as session:
            session.add(
                MappingOverrideRow(
                    id=str(uuid.uuid4()),
                    dataset_id=request.dataset_id,
                    catalog_product_id=product_id,
                    material_id=request.material_id if request.status == "confirmed" else None,
                    status=request.status,
                    basis=request.basis,
                    confirmed_by=request.confirmed_by,
                    version=version,
                    kb_version=catalog.kb.version,
                    created_at=self.clock(),
                )
            )
        return self._mapping_dto(catalog, self.effective_mappings(catalog)[product_id])

    # ----------------------------------------------------------------- catalog
    def _product_dto(self, catalog: DatasetCatalog, product: Product, mappings: dict[str, MappingDecision] | None = None) -> CatalogProduct:
        mapping = (mappings or {}).get(product.product_id)
        kb = catalog.kb
        return CatalogProduct(
            catalog_product_id=product.product_id,
            name=product.name,
            category=product.kind,
            kind=product.kind,
            prices=[
                CatalogPrice(
                    price_type=p.price_type,  # type: ignore[arg-type]
                    amount_tg=money_str(p.amount) if p.amount is not None else None,
                    minimum_quantity=p.minimum_quantity,
                    unit=p.unit,
                    source_field=p.source_field,
                )
                for p in product.prices
            ],
            evidence=[Evidence(source=kb.source, source_version=kb.version, record_id=product.product_id, field="название")],
            attributes=dict(product.attributes),
            unknown_fields=dict(product.unknown_fields),
            kb_version=kb.version,
            mapping=self._mapping_dto(catalog, mapping) if mapping else None,
        )

    def list_catalog(self, dataset_id: str, kb_version: str | None = None, kind: str | None = None) -> list[CatalogProduct]:
        catalog = self._current(dataset_id, kb_version)
        mappings = self.effective_mappings(catalog)
        return [self._product_dto(catalog, p, mappings) for p in catalog.kb.products if kind in (None, p.kind)]

    def get_product(self, dataset_id: str, product_id: str) -> CatalogProduct:
        catalog = self.catalog_for(dataset_id)
        product = catalog.kb.product(product_id)
        if product is None:
            raise IntelligenceError(404, "PRODUCT_NOT_FOUND", f"Позиция {product_id} не найдена в этом наборе.")
        return self._product_dto(catalog, product, self.effective_mappings(catalog))

    def search_catalog(self, dataset_id: str, query: str) -> CatalogSearchResult:
        catalog = self.catalog_for(dataset_id)
        result = match_products(catalog.kb, query)
        mappings = self.effective_mappings(catalog)
        clarification = None
        if result.status == "ambiguous":
            clarification = "Найдено несколько позиций; уточните вид, цвет, толщину или формат."
        elif result.status == "not_found":
            clarification = "Позиция в базе знаний не найдена; цену уточнит менеджер."
        status = result.status if result.status != "exact" or result.candidates[0].complete else "best"
        return CatalogSearchResult(
            query=query,
            status=status,  # type: ignore[arg-type]
            candidates=[self._product_dto(catalog, c.product, mappings) for c in result.candidates[:6]],
            clarification=clarification,
            kb_version=catalog.kb.version,
        )

    def list_rules(self, dataset_id: str) -> list[CatalogRule]:
        kb = self.catalog_for(dataset_id).kb
        return [CatalogRule(rule_id=r.rule_id, text=r.text, topics=list(r.topics), kb_version=kb.version) for r in kb.rules]

    def price_versions(self, dataset_id: str) -> list[PriceVersion]:
        current = self.catalog_for(dataset_id).kb
        try:
            history = self.sources.kb_history(dataset_id)
        except DatasetNotFound:
            raise IntelligenceError(404, "DATASET_NOT_FOUND", f"Набор данных {dataset_id} не найден.") from None
        versions = []
        for document in history:
            kb = self._kb_cache.get(document.sha256) or parse_knowledge_base(document.content, document.name)
            versions.append(
                PriceVersion(kb_version=kb.version, sha256=kb.sha256, source=document.origin,
                             product_count=len(kb.products), current=kb.version == current.version)
            )
        return versions

    @staticmethod
    def normalize_dimensions(text: str) -> DimensionNormalizeResult:
        status, proposal, message = parse_dimension_text(text)
        if proposal is None:
            return DimensionNormalizeResult(status=status, source_text=text, message_ru=message)  # type: ignore[arg-type]
        return DimensionNormalizeResult(
            status="ok",
            dimensions=Dimensions(length_mm=proposal.length_mm, width_mm=proposal.width_mm),
            source_text=proposal.source_text,
            source_unit=proposal.source_unit,  # type: ignore[arg-type]
            normalized_text=proposal.normalized_text,
            message_ru=None if proposal.source_unit == "mm" else f"«{proposal.source_text}» → {proposal.normalized_text}",
        )

    # ----------------------------------------------------------------- quotes
    def _price(self, catalog: DatasetCatalog, request: QuoteRequest) -> tuple[Product, PricingResult, MappingDecision | None]:
        product = catalog.kb.product(request.catalog_product_id)
        if product is None:
            raise IntelligenceError(
                404, "PRODUCT_NOT_FOUND", f"Позиция {request.catalog_product_id} не найдена в версии {catalog.kb.version}.",
                field_errors=[{"field": "catalog_product_id", "message_ru": "нет в каталоге"}],
            )
        mapping = self.effective_mappings(catalog).get(product.product_id)
        thickness = None
        if mapping and mapping.status == "confirmed" and mapping.material_id and catalog.materials:
            record = catalog.materials.get(mapping.material_id)
            thickness = record.thickness_mm if record else None
        processing = request.processing
        try:
            result = calculate(
                catalog.kb,
                PricingInput(
                    product,
                    request.dimensions.length_mm if request.dimensions else None,
                    request.dimensions.width_mm if request.dimensions else None,
                    request.quantity,
                    processing.kind,
                    processing.sides,
                    tuple(processing.selected_sides),
                    request.price_basis,
                    thickness,
                ),
            )
        except PricingInputError as exc:
            raise IntelligenceError(422, "VALIDATION_ERROR", exc.message_ru, field_errors=[{"field": exc.field_name, "message_ru": exc.message_ru}]) from None
        return product, result, mapping

    def _inventory(self, catalog: DatasetCatalog, request: QuoteRequest, mapping: MappingDecision | None):
        if request.inventory_mode == "none" or request.dimensions is None:
            return "not_requested", [], []
        if mapping is None or mapping.status != "confirmed" or not mapping.material_id:
            return "mapping_required", [], [f"mapping_{mapping.status if mapping else 'missing'}"]
        if self.inventory is None:
            return "service_unavailable", [], ["inventory_port_not_wired"]
        try:
            found = self.inventory.find_candidates(
                FindRequest(
                    dataset_id=catalog.dataset_id,
                    material_id=mapping.material_id,
                    dimensions=request.dimensions,
                    premium=request.premium,
                    inventory_mode="replan" if request.inventory_mode == "replan" else "free_whole_remnants",
                )
            )
        except ServiceUnavailable as exc:
            return "service_unavailable", [], [str(exc)]
        refs = [
            RemnantCandidateRef(
                remnant_id=c.remnant_id, remnant_version=c.remnant_version, x_mm=c.x_mm, y_mm=c.y_mm, rot=c.rot, location_raw=c.location_raw
            )
            for c in found.candidates[:5]
        ]
        return ("checked" if refs else "unavailable"), refs, list(found.reason_codes)

    def _build_quote(self, catalog, request: QuoteRequest, product, result: PricingResult, mapping, *, quote_id, revision,
                     created_at, inventory=("not_requested", [], [])) -> Quote:
        status = "calculated" if result.complete else "needs_review"
        inventory_status, refs, reasons = inventory
        mapping_status = mapping.status if mapping else "unmapped"
        source_versions = {"kb": catalog.kb.version, "kb_sha256": catalog.kb.sha256, "pricing": "pricing-v1"}
        if catalog.materials:
            source_versions["materials"] = catalog.materials.version
        if mapping:
            source_versions["mapping"] = f"{mapping.basis}@{mapping.version}"
        return Quote(
            dataset_id=catalog.dataset_id,
            quote_id=quote_id,
            revision=revision,
            status=status,  # type: ignore[arg-type]
            components=[
                QuoteLine(
                    label=line.label,
                    amount_tg=money_str(line.amount),
                    evidence=line.evidence,
                    component=line.component,  # type: ignore[arg-type]
                    quantity=line.quantity,
                    unit_price_tg=money_str(line.unit_price),
                    unit=line.unit,
                    measure_per_unit=f"{line.measure_per_unit:f}" if line.measure_per_unit is not None else None,
                    exact_amount_tg=f"{line.exact:f}",
                    formula=line.formula,
                )
                for line in result.lines
            ],
            total_tg=money_str(result.total),
            preliminary=True,
            clarification=result.clarification,
            material_mapping_status=mapping_status,  # type: ignore[arg-type]
            material_id=mapping.material_id if mapping and mapping.status == "confirmed" else None,
            catalog_product_id=product.product_id,
            product_name=product.name,
            kb_version=catalog.kb.version,
            customer_id=request.customer_id,
            dimensions=request.dimensions,
            quantity=request.quantity,
            processing=request.processing,
            price_basis=result.price_basis,
            confirmed_parameters=result.confirmed_parameters,
            assumptions=list(request.assumptions) + result.assumptions,
            unknown_components=[
                UnknownComponent(component=u.component, reason_code=u.reason_code, message_ru=u.message_ru, evidence=u.evidence)
                for u in result.unknowns
            ],
            known_subtotal_tg=money_str(result.known_subtotal),
            rounding_policy=ROUNDING_POLICY,
            source_versions=source_versions,
            inventory_status=inventory_status,  # type: ignore[arg-type]
            candidate_refs=refs,
            inventory_reason_codes=reasons,
            created_at=created_at,
            evidence=[Evidence(source=catalog.kb.source, source_version=catalog.kb.version, record_id=product.product_id, field="название")],
        )

    def _store_revision(self, session, quote: Quote, request: QuoteRequest) -> None:
        session.add(
            QuoteRevisionRow(
                id=str(uuid.uuid4()),
                dataset_id=quote.dataset_id,
                quote_id=quote.quote_id,
                revision=quote.revision,
                status=quote.status,
                kb_version=quote.kb_version or "",
                customer_id=quote.customer_id,
                request_json=request.model_dump_json(),
                quote_json=quote.model_dump_json(),
                created_at=quote.created_at or self.clock(),
            )
        )

    def calculate_quote(self, request: QuoteRequest) -> Quote:
        catalog = self._current(request.dataset_id, request.kb_version)
        product, result, mapping = self._price(catalog, request)
        inventory = self._inventory(catalog, request, mapping)
        quote = self._build_quote(
            catalog, request, product, result, mapping,
            quote_id=str(uuid.uuid4()), revision=1, created_at=self.clock(), inventory=inventory,
        )
        with self.session_factory.begin() as session:
            self._store_revision(session, quote, request)
        return quote

    quote = calculate_quote  # IntelligencePort.quote

    def _rows(self, session, dataset_id: str, quote_id: str) -> list[QuoteRevisionRow]:
        rows = session.scalars(
            select(QuoteRevisionRow)
            .where(QuoteRevisionRow.dataset_id == dataset_id, QuoteRevisionRow.quote_id == quote_id)
            .order_by(QuoteRevisionRow.revision)
        ).all()
        if not rows:
            raise IntelligenceError(404, "QUOTE_NOT_FOUND", "Предложение не найдено в этом наборе данных.")
        return list(rows)

    def _view(self, row: QuoteRevisionRow, current_kb: str | None) -> Quote:
        quote = Quote.model_validate_json(row.quote_json)
        quote.status = row.status  # type: ignore[assignment]
        quote.confirmed_at, quote.confirmed_by = row.confirmed_at, row.confirmed_by
        quote.stale = current_kb is not None and row.kb_version != current_kb
        return quote

    def get_quote(self, quote_id: str, dataset_id: str, revision: int | None = None) -> Quote:
        current = self.catalog_for(dataset_id).kb.version
        with self.session_factory() as session:
            rows = self._rows(session, dataset_id, quote_id)
        row = rows[-1] if revision is None else next((r for r in rows if r.revision == revision), None)
        if row is None:
            raise IntelligenceError(404, "QUOTE_REVISION_NOT_FOUND", f"Ревизия {revision} не найдена.")
        return self._view(row, current)

    def list_revisions(self, quote_id: str, dataset_id: str) -> list[Quote]:
        current = self.catalog_for(dataset_id).kb.version
        with self.session_factory() as session:
            rows = self._rows(session, dataset_id, quote_id)
        return [self._view(row, current) for row in rows]

    @staticmethod
    def _diff(before: Quote, after: Quote, changed: list[str]) -> QuoteDiff:
        components = []
        before_lines = {line.component: line.amount_tg for line in before.components}
        after_lines = {line.component: line.amount_tg for line in after.components}
        for component in dict.fromkeys(list(before_lines) + list(after_lines)):
            if before_lines.get(component) != after_lines.get(component):
                components.append(QuoteLineDiff(component=component or "line", before_tg=before_lines.get(component), after_tg=after_lines.get(component)))
        return QuoteDiff(
            from_revision=before.revision, to_revision=after.revision, changed_fields=changed, lines=components,
            total_before_tg=before.total_tg, total_after_tg=after.total_tg,
        )

    def revise_quote(self, quote_id: str, request: QuoteReviseRequest) -> Quote:
        with self.session_factory() as session:
            rows = self._rows(session, request.dataset_id, quote_id)
        latest = rows[-1]
        if request.expected_revision != latest.revision:
            raise IntelligenceError(409, "REVISION_CONFLICT", "Предложение уже изменено; обновите данные.", conflict_objects=[f"{quote_id}@{latest.revision}"])
        if latest.status == "cancelled":
            raise IntelligenceError(409, "QUOTE_CANCELLED", "Отмененное предложение не пересчитывается.")
        base = QuoteRequest.model_validate_json(latest.request_json)
        changes = request.changes
        changed: list[str] = []
        data = base.model_dump()
        for field in ("catalog_product_id", "dimensions", "quantity", "processing", "price_basis", "customer_id"):
            value = getattr(changes, field)
            if value is not None:
                new = value.model_dump() if hasattr(value, "model_dump") else value
                if data.get(field) != new:
                    changed.append(field)
                data[field] = new
        catalog = self.catalog_for(request.dataset_id)
        if changes.kb_version:
            target = changes.kb_version
        elif request.reprice_current_kb:
            target = catalog.kb.version
        else:
            target = latest.kb_version
        if target != latest.kb_version:
            changed.append("kb_version")
        if target != catalog.kb.version:
            raise IntelligenceError(
                409, "STALE_KB_VERSION", f"Расчет возможен только по текущей версии базы знаний {catalog.kb.version}.",
                conflict_objects=[catalog.kb.version],
            )
        data["kb_version"] = target
        new_request = QuoteRequest.model_validate(data)
        product, result, mapping = self._price(catalog, new_request)
        inventory = self._inventory(catalog, new_request, mapping)
        quote = self._build_quote(
            catalog, new_request, product, result, mapping,
            quote_id=quote_id, revision=latest.revision + 1, created_at=self.clock(), inventory=inventory,
        )
        previous = self._view(latest, catalog.kb.version)
        quote.diff = self._diff(previous, quote, changed)
        with self.session_factory.begin() as session:
            row = session.get(QuoteRevisionRow, latest.id)
            if row.status not in {"confirmed", "cancelled", "superseded"}:
                row.status = "superseded"
            self._store_revision(session, quote, new_request)
        return quote

    def confirm_quote(self, quote_id: str, request: QuoteConfirmRequest, idempotency_key: str | None = None) -> Quote:
        body_hash = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        catalog = self.catalog_for(request.dataset_id)
        with self.session_factory() as session:
            rows = self._rows(session, request.dataset_id, quote_id)
        latest = rows[-1]
        target = next((r for r in rows if r.revision == request.expected_revision), None)
        if target is None:
            raise IntelligenceError(404, "QUOTE_REVISION_NOT_FOUND", "Ревизия не найдена.")
        if target.status == "confirmed":
            same_key = idempotency_key is None or target.confirm_key in (None, idempotency_key)
            if same_key and target.confirm_body_sha256 == body_hash:
                return self._view(target, catalog.kb.version)
            raise IntelligenceError(409, "ALREADY_CONFIRMED", "Ревизия уже подтверждена другим запросом.", conflict_objects=[f"{quote_id}@{target.revision}"])
        if target.revision != latest.revision:
            raise IntelligenceError(409, "REVISION_CONFLICT", "Подтверждать можно только последнюю ревизию.", conflict_objects=[f"{quote_id}@{latest.revision}"])
        if target.status != "calculated":
            raise IntelligenceError(409, "QUOTE_NOT_CONFIRMABLE", "Есть неизвестные позиции или ревизия не активна; нужна проверка менеджера.")
        if target.kb_version != catalog.kb.version:
            raise IntelligenceError(409, "STALE_KB_VERSION", "Прайс изменился после расчета; сначала пересчитайте.", conflict_objects=[catalog.kb.version])
        quote = self._view(target, catalog.kb.version)
        reasons = list(quote.inventory_reason_codes)
        if quote.candidate_refs:
            stored_request = QuoteRequest.model_validate_json(target.request_json)
            status, refs, fresh_reasons = self._inventory(catalog, stored_request, self.effective_mappings(catalog).get(quote.catalog_product_id or ""))
            fresh = {(r.remnant_id, r.remnant_version) for r in refs}
            if not fresh or (quote.candidate_refs[0].remnant_id, quote.candidate_refs[0].remnant_version) not in fresh:
                reasons.append("candidate_changed_recheck_required")
            quote.candidate_refs, quote.inventory_status = refs, status  # type: ignore[assignment]
            reasons.extend(fresh_reasons)
        quote.inventory_reason_codes = list(dict.fromkeys(reasons))
        quote.status = "confirmed"
        quote.confirmed_at, quote.confirmed_by = self.clock(), request.confirmed_by
        with self.session_factory.begin() as session:
            row = session.get(QuoteRevisionRow, target.id)
            if row.status != "calculated":
                raise IntelligenceError(409, "ALREADY_CONFIRMED", "Ревизия изменена параллельно.")
            row.status = "confirmed"
            row.confirmed_at, row.confirmed_by = quote.confirmed_at, quote.confirmed_by
            row.confirm_key, row.confirm_body_sha256 = idempotency_key, body_hash
            row.quote_json = quote.model_dump_json()
        return quote

    def cancel_quote(self, quote_id: str, request: QuoteCancelRequest) -> Quote:
        with self.session_factory() as session:
            rows = self._rows(session, request.dataset_id, quote_id)
        latest = rows[-1]
        if latest.revision != request.expected_revision:
            raise IntelligenceError(409, "REVISION_CONFLICT", "Предложение уже изменено.", conflict_objects=[f"{quote_id}@{latest.revision}"])
        if latest.status == "cancelled":
            return self._view(latest, None)
        with self.session_factory.begin() as session:
            row = session.get(QuoteRevisionRow, latest.id)
            row.status = "cancelled"
        return self.get_quote(quote_id, request.dataset_id)

    # ----------------------------------------------------------------- assistant
    def _engine(self, catalog: DatasetCatalog, allow_ai: bool = True) -> AssistantEngine:
        cache = self._answer_caches.setdefault(catalog.dataset_id, AnswerCache())
        return AssistantEngine(
            catalog.kb, self.effective_mappings(catalog), dataset_id=catalog.dataset_id,
            runtime=self.runtime if allow_ai else None, inventory=self.inventory, crm=self.crm, scenario=self.scenario, cache=cache,
        )

    async def assistant_turn(self, turn: AssistantTurn, correlation_id: str | None = None) -> AssistantReply:
        catalog = self._current(turn.dataset_id, turn.kb_version)
        conversation_id = turn.conversation_id
        context = TurnContext(customer_id=turn.customer_id)
        turn_index = 0
        notes: list[str] = []
        quote_id: str | None = None
        quote_revision = 0
        with self.session_factory() as session:
            if conversation_id:
                row = session.get(ConversationRow, conversation_id)
                if row is None or row.dataset_id != turn.dataset_id:
                    raise IntelligenceError(404, "CONVERSATION_NOT_FOUND", "Диалог не найден в этом наборе данных.")
                stored = json.loads(row.context_json)
                if turn.customer_id and row.customer_id and turn.customer_id != row.customer_id:
                    notes.append("Клиент изменен: прежние параметры и цена не переносятся.")
                else:
                    context = TurnContext.from_dict(stored.get("context"))
                    quote_id = stored.get("quote_id")
                    quote_revision = int(stored.get("quote_revision", 0))
                turn_index = row.version
        engine = self._engine(catalog, turn.allow_ai)
        result = await engine.turn(
            turn.text, context, inventory_mode=turn.inventory_mode, allow_ai=turn.allow_ai, correlation_id=correlation_id
        )
        local = result.local
        pricing = None
        if result.answer_path == "llm_tools" and result.tool_context is not None:
            pricing = result.tool_context.last_quote
        elif result.answer_path != "llm_tools":
            pricing = local.pricing
        quote_dto = None
        new_context = local.context if result.answer_path != "llm_tools" else context
        if pricing is not None and pricing.lines or (pricing is not None and pricing.unknowns and pricing.product):
            request = QuoteRequest(
                dataset_id=turn.dataset_id,
                catalog_product_id=pricing.product.product_id,
                dimensions=Dimensions(length_mm=int(pricing.confirmed_parameters["length_mm"]), width_mm=int(pricing.confirmed_parameters["width_mm"]))
                if "length_mm" in pricing.confirmed_parameters else None,
                quantity=int(pricing.confirmed_parameters["quantity"]) if "quantity" in pricing.confirmed_parameters else None,
                processing=_processing_from(pricing),
                kb_version=catalog.kb.version,
                customer_id=turn.customer_id,
                price_basis=pricing.price_basis if pricing.price_basis in {"per_m2", "per_sheet", "unit"} else "auto",
                inventory_mode="none",
                assumptions=list(local.assumptions)[:20],
            )
            mapping = self.effective_mappings(catalog).get(pricing.product.product_id)
            inventory = (
                local.inventory_status,
                [RemnantCandidateRef(**{k: c[k] for k in ("remnant_id", "remnant_version", "x_mm", "y_mm", "rot", "location_raw")}) for c in local.candidates[:5]],
                local.inventory_reason_codes,
            ) if result.answer_path != "llm_tools" else ("not_requested", [], [])
            if quote_id is None:
                quote_id, quote_revision = str(uuid.uuid4()), 0
            quote_revision += 1
            quote_dto = self._build_quote(
                catalog, request, pricing.product, pricing, mapping, quote_id=quote_id, revision=quote_revision,
                created_at=self.clock(), inventory=inventory,
            )
        card = WorkingCard(
            intent=local.intent,
            catalog_product_id=local.product.product_id if local.product else None,
            product_name=local.product.name if local.product else None,
            confirmed_parameters={k: v for k, v in local.context.to_dict().items() if k != "pending_query"},
            assumptions=notes + local.assumptions,
            missing_parameters=local.missing_parameters,
            normalized_dimensions=local.normalized_dimensions,
            facts=[
                VerifiedFact(fact_id=f.fact_id, kind=f.kind, value=f.value, unit=f.unit, source_ref=f.source_ref)
                for f in (result.tool_context.facts.facts if result.tool_context else local.facts.facts)[:40]
            ],
            alternatives=local.alternatives,
            needs_manager=local.needs_manager or (result.llm.needs_manager if result.llm else False),
        )
        traces = local.tool_calls if result.answer_path != "llm_tools" else []
        tool_records = [
            ToolCallRecord(tool=t.tool, status=t.status if t.status in {"ok", "rejected", "error", "unavailable"} else "ok",
                           arguments={k: v for k, v in t.arguments.items() if isinstance(v, (str, int, float, bool)) or v is None},
                           summary=t.summary[:300], error_code=t.error_code)
            for t in traces
        ]
        if result.llm:
            for execution in result.llm.executions:
                tool_records.append(
                    ToolCallRecord(tool=execution.name, status=execution.status, arguments={k: v for k, v in execution.arguments.items()
                                   if isinstance(v, (str, int, float, bool)) or v is None}, summary=execution.result_json()[:300],
                                   error_code=execution.error_code)
                )
        evidence = list({(e.source, e.source_version, e.record_id, e.field): e for e in local.evidence}.values())[:30]
        created = self.clock()
        conversation_id = conversation_id or str(uuid.uuid4())
        reply = AssistantReply(
            conversation_id=conversation_id,
            answer=result.answer,
            clarification=result.clarification,
            quote=quote_dto,
            evidence=evidence,
            mode=result.mode,  # type: ignore[arg-type]
            provider=result.provider,
            model_id=result.model_id,
            answer_path=result.answer_path,  # type: ignore[arg-type]
            status=result.status,  # type: ignore[arg-type]
            card=card,
            tool_calls=tool_records,
            verifier_status=result.verifier_status,  # type: ignore[arg-type]
            ai_unavailable_reason=result.ai_unavailable_reason,
            turn_index=turn_index,
            latency_ms=result.latency_ms,
        )
        with self.session_factory.begin() as session:
            row = session.get(ConversationRow, conversation_id)
            context_payload = json.dumps(
                {"context": new_context.to_dict(), "quote_id": quote_id, "quote_revision": quote_revision}, ensure_ascii=False
            )
            if row is None:
                row = ConversationRow(
                    conversation_id=conversation_id, dataset_id=turn.dataset_id, customer_id=turn.customer_id,
                    context_json=context_payload, version=0, created_at=created, updated_at=created,
                )
                session.add(row)
            if notes:
                row.customer_id = turn.customer_id
            row.context_json = context_payload
            row.version = turn_index + 1
            row.updated_at = created
            session.add(TurnRow(id=str(uuid.uuid4()), conversation_id=conversation_id, turn_index=turn_index,
                                user_text=turn.text, reply_json=reply.model_dump_json(), created_at=created))
            if quote_dto is not None:
                previous = session.scalars(
                    select(QuoteRevisionRow).where(
                        QuoteRevisionRow.dataset_id == turn.dataset_id, QuoteRevisionRow.quote_id == quote_dto.quote_id,
                        QuoteRevisionRow.status.in_(["calculated", "needs_review"]),
                    )
                ).all()
                for old in previous:
                    old.status = "superseded"
                self._store_revision(session, quote_dto, request)
        return reply

    def get_conversation(self, conversation_id: str, dataset_id: str) -> Conversation:
        with self.session_factory() as session:
            row = session.get(ConversationRow, conversation_id)
            if row is None or row.dataset_id != dataset_id:
                raise IntelligenceError(404, "CONVERSATION_NOT_FOUND", "Диалог не найден в этом наборе данных.")
            turns = session.scalars(select(TurnRow).where(TurnRow.conversation_id == conversation_id).order_by(TurnRow.turn_index)).all()
            return Conversation(
                conversation_id=row.conversation_id,
                dataset_id=row.dataset_id,
                customer_id=row.customer_id,
                context=json.loads(row.context_json).get("context", {}),
                turns=[
                    ConversationTurnView(turn_index=t.turn_index, user_text=t.user_text, reply=AssistantReply.model_validate_json(t.reply_json), created_at=t.created_at)
                    for t in turns
                ],
            )

    # ----------------------------------------------------------------- batch: questions
    async def answer_questions(self, request: AnswerBatchRequest) -> AnswerBatchResult:
        catalog = self._current(request.dataset_id, request.kb_version)
        engine = self._engine(catalog, request.allow_ai)
        seen: set[str] = set()
        rows: list[AnswerRow] = []
        blockers: list[str] = []
        for question in request.questions:
            digest = hashlib.sha256(question.question.encode("utf-8")).hexdigest()
            if question.id in seen:
                blockers.append(f"duplicate_id:{question.id}")
            seen.add(question.id)
            try:
                result = await engine.turn(question.question, TurnContext(), inventory_mode="none", allow_ai=request.allow_ai)
            except Exception as exc:  # one failed row never hides the others
                rows.append(AnswerRow(id=question.id, answer="", status="failed", answer_path="error", input_sha256=digest))
                blockers.append(f"failed:{question.id}:{type(exc).__name__}")
                continue
            rows.append(
                AnswerRow(
                    id=question.id,
                    answer=result.answer,
                    status=result.status if result.status in {"answered", "clarification", "manager_handoff", "limited"} else "answered",  # type: ignore[arg-type]
                    answer_path=result.answer_path,
                    provider=result.provider,
                    model_id=result.model_id,
                    input_sha256=digest,
                    evidence=result.local.evidence[:10],
                )
            )
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.status] = counts.get(row.status, 0) + 1
        return AnswerBatchResult(
            dataset_id=request.dataset_id, kb_version=catalog.kb.version, answers=rows,
            complete=not any(b.startswith(("failed", "duplicate")) for b in blockers) and all(r.answer for r in rows),
            counts=counts, export_blockers=blockers,
        )

    # ----------------------------------------------------------------- quality
    def _check(self, catalog: DatasetCatalog, dialog_id: str, client: str, manager: str) -> DialogVerdict:
        verdict = check_dialog(catalog.kb, dialog_id, client, manager)
        with self.session_factory.begin() as session:
            session.add(
                QualityCheckRow(
                    id=str(uuid.uuid4()), dataset_id=catalog.dataset_id, dialog_id=dialog_id, input_sha256=verdict.input_sha256 or "",
                    kb_version=catalog.kb.version, verdict=verdict.verdict, correct=verdict.correct,
                    result_json=verdict.model_dump_json(), created_at=self.clock(),
                )
            )
        return verdict

    def check_dialog_sync(self, request: DialogRequest) -> DialogVerdict:
        catalog = self._current(request.dataset_id, request.kb_version)
        return self._check(catalog, request.id, request.client, request.manager)

    async def check_dialog(self, request: DialogRequest) -> DialogVerdict:  # IntelligencePort
        return self.check_dialog_sync(request)

    def check_dialogs(self, request: DialogBatchRequest) -> DialogBatchResult:
        catalog = self._current(request.dataset_id, request.kb_version)
        verdicts = []
        blockers = []
        seen: set[str] = set()
        for dialog in request.dialogs:
            if dialog.id in seen:
                blockers.append(f"duplicate_id:{dialog.id}")
            seen.add(dialog.id)
            verdict = self._check(catalog, dialog.id, dialog.client, dialog.manager)
            if verdict.verdict == "NEEDS_REVIEW":
                blockers.append(f"needs_review:{dialog.id}")
            verdicts.append(verdict)
        counts = {k: sum(1 for v in verdicts if v.verdict == k) for k in ("OK", "ERROR", "NEEDS_REVIEW")}
        return DialogBatchResult(
            dataset_id=request.dataset_id, kb_version=catalog.kb.version, verdicts=verdicts,
            complete=not blockers, counts=counts, export_blockers=blockers,
        )

    # ----------------------------------------------------------------- AI profile / usage
    def ai_profile(self) -> AIProfileView:
        runtime = self.runtime
        if runtime is None:
            return AIProfileView(profile="none", provider="none", model_id=None, mode="free_only", key_configured=False)
        profile = runtime.profile
        primary = profile.primary
        return AIProfileView(
            profile=profile.name,
            provider=primary.provider if primary else "none",
            model_id=primary.model_id if primary else None,
            mode=profile.mode,
            fallback_models=[ref.label for ref in profile.fallbacks],
            key_configured=bool(primary and runtime.key_configured.get(primary.provider)),
            budget_limit_usd=f"{profile.budget_usd:f}",
            limits={"rpm": profile.rpm, "tpm": profile.tpm, "rpd": profile.rpd, "max_tool_iterations": profile.max_tool_iterations,
                    "max_retries": profile.max_retries, "max_concurrency": profile.max_concurrency},
        )

    async def check_ai(self, request: AICheckRequest) -> AICheckResult:
        runtime = self.runtime
        view = self.ai_profile()
        base = dict(profile=view.profile, provider=view.provider, model_id=view.model_id, live_checked=False)
        if runtime is None or runtime.status in {"disabled", "no_key"}:
            return AICheckResult(status="no_key", message_ru=(runtime.reason_ru if runtime else "AI не настроен."), **base)
        if runtime.status == "invalid_profile":
            return AICheckResult(status="invalid_profile", message_ru=runtime.reason_ru or "Профиль некорректен.", **base)
        assert runtime.client is not None
        capabilities = {}
        for label, provider in runtime.client.providers.items():
            if label in runtime.client.chain():
                capabilities = provider.capabilities()
                break
        quota = {"rpm": runtime.profile.rpm, "tpm": runtime.profile.tpm, "rpd": runtime.profile.rpd}
        if not request.live:
            return AICheckResult(status="available", capabilities=capabilities, quota=quota,
                                 message_ru="Профиль корректен, ключ задан; сетевая проверка не выполнялась.", **base)
        import time as _time

        started = _time.monotonic()
        try:
            outcome = await runtime.client.call(
                ProviderRequest(system="Ответь одним словом: ok", messages=[ChatMessage(role="user", text="ping")],
                                max_output_tokens=16, purpose="settings_check"),
                deadline=_time.monotonic() + 20,
            )
        except ProviderError as exc:
            status = {"auth": "access_denied", "rate_limit": "rate_limited"}.get(exc.kind, "unavailable")
            return AICheckResult(status=status, capabilities=capabilities, quota=quota, message_ru=str(exc), **{**base, "live_checked": True})  # type: ignore[arg-type]
        return AICheckResult(
            status="available", capabilities=capabilities, quota=quota,
            message_ru=f"Ответ получен от {outcome.response.model_id}.",
            latency_ms=int((_time.monotonic() - started) * 1000),
            **{**base, "model_id": outcome.response.model_id, "live_checked": True},
        )

    def usage_summary(self, since: str | None = None) -> dict[str, Any]:
        with self.session_factory() as session:
            query = select(AICallRow)
            if since:
                query = query.where(AICallRow.created_at >= since)
            rows = session.scalars(query).all()
        latencies = sorted(r.latency_ms for r in rows if r.latency_ms is not None and r.status == "ok")
        costs = [Decimal(r.cost_usd) for r in rows if r.cost_usd is not None]

        def pct(values: list[int], q: float) -> int | None:
            if not values:
                return None
            index = min(len(values) - 1, max(0, int(round(q * (len(values) - 1)))))
            return values[index]

        by_purpose: dict[str, int] = {}
        by_model: dict[str, int] = {}
        for row in rows:
            by_purpose[row.purpose] = by_purpose.get(row.purpose, 0) + 1
            by_model[f"{row.provider}:{row.model_id}"] = by_model.get(f"{row.provider}:{row.model_id}", 0) + 1
        return {
            "calls": len(rows),
            "ok": sum(1 for r in rows if r.status == "ok"),
            "errors": {kind: sum(1 for r in rows if r.error_kind == kind) for kind in {r.error_kind for r in rows if r.error_kind}},
            "by_purpose": by_purpose,
            "by_model": by_model,
            "input_tokens": sum(r.input_tokens or 0 for r in rows),
            "output_tokens": sum(r.output_tokens or 0 for r in rows),
            "thought_tokens": sum(r.thought_tokens or 0 for r in rows),
            "calls_with_unknown_tokens": sum(1 for r in rows if r.status == "ok" and r.input_tokens is None),
            "latency_ms_p50": int(statistics.median(latencies)) if latencies else None,
            "latency_ms_p95": pct(latencies, 0.95),
            "cost_usd_known_sum": f"{sum(costs, Decimal(0)):f}" if costs else None,
            "calls_with_unknown_cost": sum(1 for r in rows if r.cost_usd is None),
            "prompt_versions": sorted({r.prompt_version for r in rows}),
            "current_prompt_version": PROMPT_VERSION,
        }


def _processing_from(pricing: PricingResult) -> Processing:
    params = pricing.confirmed_parameters
    kind = params.get("processing", "none")
    if kind not in {"none", "euro_edge", "facet", "sandblast"}:
        kind = "none"
    sides = params.get("edge_sides", "all")
    if sides == "all" or kind != "euro_edge":
        return Processing(kind=kind)  # type: ignore[arg-type]
    selected = [s for s in sides.split(",") if s in {"left", "right", "top", "bottom"}]
    return Processing(kind=kind, sides="selected", selected_sides=selected)  # type: ignore[arg-type]
