"""Atomic U06 coordinator and immutable ledger. C2 is the only inventory writer."""

from decimal import Decimal

from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from glassflow.contracts.material_use import (
    MaterialUseAssessment,
    MaterialUseReceipt,
    MaterialUseRecord,
    MaterialUseScope,
    MaterialUseSummary,
)
from glassflow.core.errors import AppError
from glassflow.core.models import MaterialUseRow, now, uid
from glassflow.core.uow import audit, canonical_hash
from glassflow.modules.platform import baskets, orders
from glassflow.modules.platform.imports import dataset


def validated(model, value):
    # Pydantic accepts existing model instances without rechecking mutated fields.
    # This boundary owns all nested types, so round-trip them before any C2 write.
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return model.model_validate(data).model_copy(deep=True)


def previous(session, body):
    row = session.scalar(select(MaterialUseRow).where(MaterialUseRow.dataset_id == body.dataset_id,
                          MaterialUseRow.subject_type == body.subject_type, MaterialUseRow.subject_id == body.subject_id))
    if row and (row.execution_ref, row.execution_version) != (body.execution_ref, body.execution_version):
        raise AppError(409, "MATERIAL_ALREADY_RECORDED", "Расход уже подтвержден; повторное списание запрещено.", conflicts=[row.id])
    return row


def source(services):
    if services.material_use is None:
        raise AppError(503, "MATERIAL_USE_UNAVAILABLE", "C2 actual-execution/consumption service не подключен.")
    return services.material_use


def scope_for(session, body):
    if dataset(session, body.dataset_id).mode != "workspace":
        raise AppError(409, "WORKSPACE_REQUIRED", "Фактический расход учитывается в рабочей копии.")
    if body.subject_type == "basket":
        subject = baskets.load(session, body.dataset_id, body.subject_id, body.expected_version)
        ready = subject.state == "handed_over"
        versions = subject.reservation.remnant_versions if subject.reservation else None
    else:
        subject = orders.load(session, body.dataset_id, body.subject_id, body.expected_version)
        ready = subject.lifecycle == "handed_over"
        versions = ({subject.reservation.remnant_id: subject.reservation.remnant_version}
                    if subject.reservation else None)
    if (not ready or not subject.facts_hash or subject.material_use_id or not subject.reservation
            or subject.reservation.state != "active"):
        raise AppError(409, "MATERIAL_USE_NOT_READY", "Нужны переданный заказ/корзина и действующий резерв материала.")
    return subject, MaterialUseScope(dataset_id=body.dataset_id, subject_type=body.subject_type,
        subject_id=body.subject_id, subject_revision=subject.revision, facts_hash=subject.facts_hash,
        reservation_id=subject.reservation.reservation_id, remnant_versions=versions)


def assess(session, body, services):
    subject, scope = scope_for(session, body)
    try:
        value = validated(MaterialUseAssessment, source(services).assess(
            session, scope.model_copy(deep=True), body.execution_ref, body.execution_version))
    except ValidationError:
        raise AppError(409, "MATERIAL_ASSESSMENT_INVALID", "C2 вернул неполные данные исполнения.") from None
    if (value.scope != scope or (value.execution_ref, value.execution_version) != (body.execution_ref, body.execution_version)):
        raise AppError(409, "MATERIAL_ASSESSMENT_SCOPE", "Исполнение относится к другому предмету/резерву/версии.")
    if body.subject_type == "basket":
        planned = subject.facts.stock
        if (value.planned_area_mm2 != planned.planned_area_mm2
                or Decimal(value.planned_material_value_tg) != Decimal(planned.planned_material_value_tg)):
            raise AppError(409, "MATERIAL_PLAN_MISMATCH", "Плановая оценка не совпала с подтвержденным совместным планом.")
    return subject, value


def preview(session, body, services):
    old = previous(session, body)
    if old:
        return MaterialUseRecord.model_validate(old.data).receipt.assessment
    return assess(session, body, services)[1]


def confirm(session, body, services, correlation):
    old = previous(session, body)
    if old:
        return old.data  # Semantic replay across keys; never calls C2 a second time.
    subject, assessment = assess(session, body, services)
    if ((assessment.planned_area_mm2 != assessment.actual_area_mm2
            or Decimal(assessment.planned_material_value_tg) != Decimal(assessment.actual_material_value_tg))
            and not body.discrepancy_reason.strip()):
        raise AppError(422, "MATERIAL_DISCREPANCY_REASON_REQUIRED", "Объясните отличие фактического использования от плана.")
    usage_id = uid()
    try:
        receipt = validated(MaterialUseReceipt, source(services).confirm(
            session, assessment.model_copy(deep=True), usage_id, body.operator, body.note))
    except ValidationError:
        raise AppError(409, "MATERIAL_RECEIPT_INVALID", "C2 не подтвердил полное списание.") from None
    if (receipt.assessment != assessment or receipt.confirmation_id != usage_id
            or set(receipt.post_remnant_versions) != set(assessment.scope.remnant_versions)
            or any(receipt.post_remnant_versions[rid] <= version for rid, version in assessment.scope.remnant_versions.items())):
        raise AppError(409, "MATERIAL_RECEIPT_MISMATCH", "Подтверждение не совпадает с проверенным исполнением.")
    if session.scalar(select(MaterialUseRow).where(MaterialUseRow.dataset_id == body.dataset_id,
                                                  MaterialUseRow.source_event_ref == receipt.source_event_ref)):
        raise AppError(409, "MATERIAL_EVENT_ALREADY_USED", "Складское событие уже учтено другим предметом.")
    receipt_hash = canonical_hash(receipt.model_dump(mode="json"))
    record = MaterialUseRecord(dataset_id=body.dataset_id, usage_id=usage_id, receipt=receipt,
        operator=body.operator, note=body.note, discrepancy_reason=body.discrepancy_reason,
        created_at=now(), receipt_hash=receipt_hash)
    data = record.model_dump(mode="json")
    scope = assessment.scope
    session.add(MaterialUseRow(id=usage_id, dataset_id=body.dataset_id, subject_type=body.subject_type,
        subject_id=body.subject_id, subject_revision=scope.subject_revision, reservation_id=scope.reservation_id,
        source_event_ref=receipt.source_event_ref, execution_ref=body.execution_ref, execution_version=body.execution_version,
        intent_hash=canonical_hash({"scope": scope.model_dump(mode="json"), "execution_ref": body.execution_ref,
                                    "execution_version": body.execution_version}),
        receipt_hash=receipt_hash, data=data, created_at=record.created_at))
    subject.material_use_id = usage_id
    subject.reservation.state = "consumed"
    if body.subject_type == "basket":
        subject.reservation.remnant_versions = receipt.post_remnant_versions
        subject.state = "completed"
        baskets.save(session, subject, "material_use", correlation, body.operator, body.discrepancy_reason)
    else:
        subject.reservation.remnant_version = receipt.post_remnant_versions[subject.reservation.remnant_id]
        subject.lifecycle = "completed"
        orders.save(session, subject, "material_use", correlation, body.operator, body.discrepancy_reason)
    audit(session, body.dataset_id, "material_use.confirm", usage_id, correlation, record=data)
    session.flush()
    return data


def listing(session, dataset_id, offset=0, limit=50):
    dataset(session, dataset_id)
    return [MaterialUseRecord.model_validate(row.data) for row in session.scalars(select(MaterialUseRow).where(
        MaterialUseRow.dataset_id == dataset_id).order_by(MaterialUseRow.created_at, MaterialUseRow.id).offset(offset).limit(limit))]


def summary(session, dataset_id):
    dataset(session, dataset_id)
    rows = list(session.scalars(select(MaterialUseRow).where(MaterialUseRow.dataset_id == dataset_id).order_by(MaterialUseRow.id)))
    records = [MaterialUseRecord.model_validate(row.data) for row in rows]
    assessments = [record.receipt.assessment for record in records]
    return MaterialUseSummary(dataset_id=dataset_id, confirmation_count=len(records),
        planned_area_mm2=sum(a.planned_area_mm2 for a in assessments), actual_area_mm2=sum(a.actual_area_mm2 for a in assessments),
        planned_material_value_tg=format(sum((Decimal(a.planned_material_value_tg) for a in assessments), Decimal(0)), "f"),
        actual_material_value_tg=format(sum((Decimal(a.actual_material_value_tg) for a in assessments), Decimal(0)), "f"),
        usage_ids=[r.usage_id for r in records], source_event_refs=[r.receipt.source_event_ref for r in records])
