"""Persistent, classified review work and read-only impact previews on the shared DB.

No method applies KB changes, sends a message or rewrites a conversation/quality record.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from glassflow.contracts.intelligence import (
    IntelligenceReviewItem,
    KnowledgeImpactPreview,
    ManagerCorrectionDraft,
)

from .catalog.kb import KnowledgeBaseError, parse_knowledge_base
from .catalog.mapping import derive_all
from .models import IntelligenceReviewRow, ManagerCorrectionRow, QuoteRevisionRow
from .quality.dialogs import _references, bulk_price_scope, check_dialog, money_string


def _error(status, code, message):
    from .service import IntelligenceError
    raise IntelligenceError(status, code, message)


def outcome_reasons(result) -> dict[str, list[str]]:
    """Do not confuse a correct policy handoff with provider/verifier failure."""
    local = result.local
    reasons: dict[str, list[str]] = {}
    missing = list(local.missing_parameters)
    pricing_missing = [p for p in missing if p in {"per_m2_price", "processing_price"}]
    parameters = [p for p in missing if p not in pricing_missing]
    if parameters:
        reasons["missing_parameter"] = parameters
    facts_missing = [f.value for f in local.facts.facts if f.kind == "unknown"]
    if pricing_missing or facts_missing:
        reasons["kb_fact"] = pricing_missing + facts_missing
    llm = result.llm
    if llm and llm.status == "provider_error":
        reasons["provider_error"] = [llm.error.kind if llm.error else "unavailable"]
    if llm and llm.status == "verifier_rejected":
        reasons["verifier_reject"] = [result.verifier_status]
    explicit_policy = local.intent in {"rule:installation", "rule:discount", "mirror_model"}
    if (local.needs_manager or explicit_policy) and not parameters and not pricing_missing and not facts_missing:
        reasons["correct_policy"] = [local.intent or "manager_confirmation_required"]
    return reasons


def record_classified_review(session, dataset_id, kb_version, user_text, flags, conversation_id, turn_index, now):
    for category, reasons in flags.items():
        fingerprint = hashlib.sha256(json.dumps(
            [dataset_id, kb_version, category, conversation_id, user_text], ensure_ascii=False).encode()).hexdigest()
        row = session.scalar(select(IntelligenceReviewRow).where(
            IntelligenceReviewRow.dataset_id == dataset_id, IntelligenceReviewRow.fingerprint == fingerprint))
        if row is not None:
            item = IntelligenceReviewItem.model_validate_json(row.payload_json)
            item.occurrences += 1
            item.version += 1
            item.updated_at = now
            row.version, row.updated_at, row.payload_json = item.version, now, item.model_dump_json()
            continue
        item = IntelligenceReviewItem(item_id=str(uuid.uuid4()), dataset_id=dataset_id, kb_version=kb_version,
            category=category, reason_codes=list(dict.fromkeys(reasons)), user_text=user_text,
            conversation_id=conversation_id, turn_index=turn_index, created_at=now, updated_at=now)
        session.add(IntelligenceReviewRow(id=item.item_id, dataset_id=dataset_id, kb_version=kb_version,
            category=category, status="open", fingerprint=fingerprint, version=1,
            payload_json=item.model_dump_json(), created_at=now, updated_at=now))


def record_accepted_batch_reviews(session, dataset_id, result):
    """Coordinator result hook: consume accepted metadata; never rerun an engine.

    Missing optional metadata from a historical accepted result is left untouched.
    Replayed accepted rows use their original content/category identity.
    """
    provenance = result.get("provenance", {})
    kb_version = provenance.get("kb_version")
    if not isinstance(kb_version, str):
        return
    allowed = {"correct_policy", "missing_parameter", "kb_fact", "provider_error", "verifier_reject"}
    for index, row in enumerate(provenance.get("answer_paths", [])):
        text, flags = row.get("review_user_text"), row.get("review_reasons")
        if not isinstance(text, str) or not isinstance(flags, dict) or not text or len(text) > 16000:
            continue
        safe = {key: value for key, value in flags.items() if key in allowed and isinstance(value, list)
                and all(isinstance(reason, str) and len(reason) <= 500 for reason in value)}
        record_classified_review(session, dataset_id, kb_version, text, safe,
                                 f"batch:{row.get('id', '')}", index, datetime.now(UTC).isoformat())


class IntelligenceReviews:
    def __init__(self, service):
        self.service = service

    def record_outcome(self, session, dataset_id, kb_version, user_text, result, conversation_id, turn_index):
        return record_classified_review(session, dataset_id, kb_version, user_text, outcome_reasons(result),
                                        conversation_id, turn_index, self.service.clock())

    def list_items(self, dataset_id, category=None, status=None):
        self.service.catalog_for(dataset_id)
        statement = select(IntelligenceReviewRow).where(IntelligenceReviewRow.dataset_id == dataset_id)
        if category:
            statement = statement.where(IntelligenceReviewRow.category == category)
        if status:
            statement = statement.where(IntelligenceReviewRow.status == status)
        with self.service.session_factory() as session:
            rows = session.scalars(statement.order_by(IntelligenceReviewRow.created_at, IntelligenceReviewRow.id)).all()
            return [IntelligenceReviewItem.model_validate_json(row.payload_json) for row in rows]

    @staticmethod
    def _row(session, item_id, dataset_id):
        row = session.get(IntelligenceReviewRow, item_id)
        if row is None or row.dataset_id != dataset_id:
            _error(404, "REVIEW_ITEM_NOT_FOUND", "Запись очереди не найдена в этом наборе данных.")
        return row

    def resolve(self, item_id, request):
        self.service.catalog_for(request.dataset_id)
        with self.service.session_factory.begin() as session:
            row = self._row(session, item_id, request.dataset_id)
            if row.version != request.expected_version:
                _error(409, "REVIEW_VERSION_CONFLICT", "Запись изменилась; перечитайте очередь.")
            item = IntelligenceReviewItem.model_validate_json(row.payload_json)
            item.status, item.resolved_by, item.resolution_note = "resolved", request.resolved_by, request.resolution_note
            item.version += 1
            item.updated_at = self.service.clock()
            result = session.execute(update(IntelligenceReviewRow).where(
                IntelligenceReviewRow.id == item_id, IntelligenceReviewRow.version == request.expected_version
            ).values(status="resolved", version=item.version, updated_at=item.updated_at, payload_json=item.model_dump_json()))
            if result.rowcount != 1:
                _error(409, "REVIEW_VERSION_CONFLICT", "Другой менеджер уже изменил запись.")
        return item

    def kb_preview(self, item_id, request):
        from glassflow.core.models import DatasetRow
        from glassflow.modules.platform.kb import kb_head

        current = self.service._current(request.dataset_id, request.expected_kb_version)
        with self.service.session_factory() as session:
            self._row(session, item_id, request.dataset_id)
            dataset = session.get(DatasetRow, request.dataset_id)
            if dataset is None or dataset.mode != "workspace":
                _error(409, "IMMUTABLE_DATASET", "Предпросмотр изменения KB разрешен только в рабочей копии.")
            head = kb_head(session, request.dataset_id)
            if head["kb_version"] != current.kb.version:
                _error(409, "STALE_KB_VERSION", "База знаний изменилась; обновите данные.")
            affected = session.scalars(select(QuoteRevisionRow).where(
                QuoteRevisionRow.dataset_id == request.dataset_id,
                QuoteRevisionRow.kb_version == current.kb.version,
                QuoteRevisionRow.status.in_(["calculated", "needs_review", "confirmed"]),
            )).all()
        raw = request.proposed_content.encode("utf-8")
        if len(raw) > 5_000_000:
            _error(422, "KB_TOO_LARGE", "KB превышает 5 МБ.")
        from glassflow.modules.platform.imports import inspect_files
        parsed, _, validation_errors, _ = inspect_files(
            [("ksm_knowledge_base.json", raw)], supply_reference=False, require_complete=False)
        if validation_errors or set(parsed) != {"kb"}:
            _error(422, "KB_INVALID", "Кандидат KB не прошел ту же проверку, которую выполняет применение.")
        try:
            proposed = parse_knowledge_base(raw)
        except KnowledgeBaseError as exc:
            _error(422, "KB_INVALID", str(exc))
        before = {p.product_id: p for p in current.kb.products}
        after = {p.product_id: p for p in proposed.products}
        changed = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
        old_rules = {r.rule_id: r for r in current.kb.rules}
        new_rules = {r.rule_id: r for r in proposed.rules}
        rules = sorted(r for r in old_rules.keys() | new_rules.keys() if old_rules.get(r) != new_rules.get(r))
        old_mappings = self.service.effective_mappings(current)
        new_mappings = derive_all(proposed, current.materials) if current.materials else {}
        def mapping_key(mapping):
            return (mapping.status, mapping.material_id) if mapping else None
        mapping_changes = sorted(p for p in old_mappings.keys() | new_mappings.keys()
                                 if mapping_key(old_mappings.get(p)) != mapping_key(new_mappings.get(p)))
        no_op = proposed.sha256 == current.kb.sha256
        return KnowledgeImpactPreview(dataset_id=request.dataset_id, item_id=item_id,
            current_kb_version=current.kb.version, expected_platform_version=head["version"],
            proposed_kb_version=proposed.version, proposed_sha256=proposed.sha256,
            changed_products=changed, changed_rules=rules, mapping_changes=mapping_changes, no_op=no_op,
            affected_quotes=[] if no_op else sorted(f"{q.quote_id}@{q.revision}" for q in affected),
            apply_path=f"/api/v1/datasets/{request.dataset_id}/kb",
            warnings=[] if no_op else ["Все текущие расчеты сохранят прежние суммы и потребуют проверки версии KB.",
                                       "Предпросмотр ничего не применяет. Загрузите ровно проверенные байты после подтверждения человеком."])

    def correction(self, request):
        catalog = self.service._current(request.dataset_id, request.kb_version)
        digest = hashlib.sha256(f"{request.client}\x1f{request.manager}".encode()).hexdigest()
        with self.service.session_factory() as session:
            existing = session.scalar(select(ManagerCorrectionRow).where(
                ManagerCorrectionRow.dataset_id == request.dataset_id, ManagerCorrectionRow.dialog_id == request.id,
                ManagerCorrectionRow.kb_version == catalog.kb.version, ManagerCorrectionRow.input_sha256 == digest))
            if existing:
                draft = ManagerCorrectionDraft.model_validate_json(existing.payload_json)
                draft.current_kb_version = catalog.kb.version
                return draft
        verdict = check_dialog(catalog.kb, request.id, request.client, request.manager)
        draft = ManagerCorrectionDraft(dataset_id=request.dataset_id, draft_id=str(uuid.uuid4()), dialog_id=request.id,
            input_sha256=digest, kb_version=catalog.kb.version, status="NEEDS_REVIEW",
            reason_code=verdict.reason_code or "ambiguous_reference", evidence=verdict.evidence,
            created_at=self.service.clock(), current_kb_version=catalog.kb.version)
        if verdict.verdict == "OK":
            draft.status = "NOT_NEEDED"
        elif verdict.verdict == "ERROR" and verdict.catalog_product_id and verdict.correct and verdict.reference_meaning:
            product = catalog.kb.product(verdict.catalog_product_id)
            refs = _references(catalog.kb, product, request.client, request.manager)
            meaning = verdict.reference_meaning
            canonical = refs.values.get(meaning)
            source = refs.evidence.get(meaning)
            units = {"per_m2": "за м²", "per_sheet": "за лист", "retail_unit": "за шт.",
                     "bulk_unit": "за шт. при оптовом пороге", "total": "за заказ"}
            applicable = True
            if meaning == "bulk_unit":
                bulk = product.price("bulk_unit")
                threshold = bulk.minimum_quantity if bulk else None
                applicable = bool(threshold and bulk_price_scope(product, request.client, request.manager) in {"eligible", "conditional"})
                if threshold:
                    units["bulk_unit"] = f"за шт. при количестве от {threshold} шт."
                if not applicable:
                    draft.reason_code = "bulk_threshold_not_confirmed"
            if applicable and canonical is not None and source is not None and money_string(canonical) == verdict.correct and meaning in units:
                draft.status = "DRAFT_VERIFIED"
                draft.catalog_product_id, draft.applicable_price_tg = product.product_id, money_string(canonical)
                draft.price_meaning, draft.unit = meaning, units[meaning]
                draft.source_ref = f"{source.source}:{source.source_version}:{source.record_id}:{source.field}"
                draft.answer = f"«{product.name}»: корректная цена {money_string(canonical)} ₸ {units[meaning]}."
        try:
            with self.service.session_factory.begin() as session:
                session.add(ManagerCorrectionRow(id=draft.draft_id, dataset_id=draft.dataset_id, dialog_id=draft.dialog_id,
                    kb_version=draft.kb_version, input_sha256=draft.input_sha256,
                    payload_json=draft.model_dump_json(), created_at=draft.created_at))
        except IntegrityError:
            # Two managers may request the same immutable draft concurrently.
            with self.service.session_factory() as session:
                existing = session.scalar(select(ManagerCorrectionRow).where(
                    ManagerCorrectionRow.dataset_id == draft.dataset_id, ManagerCorrectionRow.dialog_id == draft.dialog_id,
                    ManagerCorrectionRow.kb_version == draft.kb_version, ManagerCorrectionRow.input_sha256 == draft.input_sha256))
                if existing is None:
                    raise
                return ManagerCorrectionDraft.model_validate_json(existing.payload_json)
        return draft

    def list_corrections(self, dataset_id, draft_id=None):
        current_version = self.service.catalog_for(dataset_id).kb.version
        with self.service.session_factory() as session:
            statement = select(ManagerCorrectionRow).where(ManagerCorrectionRow.dataset_id == dataset_id)
            if draft_id:
                statement = statement.where(ManagerCorrectionRow.id == draft_id)
            rows = session.scalars(statement.order_by(ManagerCorrectionRow.created_at, ManagerCorrectionRow.id)).all()
            if draft_id and not rows:
                _error(404, "CORRECTION_NOT_FOUND", "Черновик не найден в этом наборе данных.")
            drafts = [ManagerCorrectionDraft.model_validate_json(row.payload_json) for row in rows]
        for draft in drafts:
            draft.is_current = draft.kb_version == current_version
            draft.current_kb_version = current_version
        if draft_id and not drafts[0].is_current:
            _error(409, "STALE_KB_VERSION", f"Прайс изменился ({current_version}); создайте новый черновик по текущей KB.")
        return drafts[0] if draft_id else drafts
