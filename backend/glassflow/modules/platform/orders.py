"""U01 state/history coordinator; quote and stock rules are delegated to canonical ports."""

from sqlalchemy import select

from glassflow.contracts.orders import OrderFacts, OrderHistory, OrderOffer, OrderSheet, WarehouseTask
from glassflow.core.errors import AppError
from glassflow.core.models import AuditRow, ObjectRow, now, uid
from glassflow.core.uow import audit, canonical_hash, get_object
from glassflow.modules.platform.imports import dataset

CUSTOMER_ERRORS = {
    "QUOTE_CUSTOMER_REQUIRED": "Клиент расчета не подтвержден. Сначала явно назначьте клиента в источнике C3.",
    "QUOTE_CUSTOMER_MISMATCH": "Расчет принадлежит другому клиенту; выберите расчет клиента заказа.",
    "QUOTE_CUSTOMER_INCONSISTENT": "Принадлежность расчета не совпадает с данными источника C3.",
}
_MISSING = object()


def quote_customer_error(facts, customer_ref):
    if facts.quote_customer_ref is None:
        return "QUOTE_CUSTOMER_REQUIRED"
    # Base C3 DTO in foundation lacks customer_id; merged C3 DTO already has it.
    # Explicit platform attestation must also agree with that canonical field.
    canonical_customer = getattr(facts.quote, "customer_id", _MISSING)
    if canonical_customer is not _MISSING and canonical_customer != facts.quote_customer_ref:
        return "QUOTE_CUSTOMER_INCONSISTENT"
    if facts.quote_customer_ref != customer_ref:
        return "QUOTE_CUSTOMER_MISMATCH"
    return None


def require_quote_customer(facts, customer_ref):
    code = quote_customer_error(facts, customer_ref)
    if code:
        raise AppError(409, code, CUSTOMER_ERRORS[code],
                       conflicts=[f"quote:{facts.quote.quote_id}:{facts.quote.revision}"])


def source(services):
    if services.order_source is None:
        raise AppError(503, "ORDER_SOURCE_UNAVAILABLE", "Источники расчета и склада не подключены.")
    return services.order_source


def project(sheet):
    sheet.offer, sheet.warehouse_task = None, None
    if (sheet.facts and not quote_customer_error(sheet.facts, sheet.customer_ref)
            and sheet.quote_state not in {"missing", "stale"} and sheet.lifecycle != "cancelled"):
        facts = sheet.facts
        sheet.offer = OrderOffer(order_id=sheet.order_id, revision=sheet.revision,
                                 facts_hash=sheet.facts_hash, quote=facts.quote,
                                 confirmed=sheet.quote_state == "confirmed")
        sheet.warehouse_task = WarehouseTask(
            order_id=sheet.order_id, revision=sheet.revision, facts_hash=sheet.facts_hash,
            material_id=facts.remnant.material_id, requested_dimensions=facts.requested_dimensions,
            quantity=facts.quantity, remnant=facts.remnant,
            location_known=bool(facts.remnant.location_raw.strip()), reservation=sheet.reservation,
            human_check=sheet.warehouse_state,
        )
    return sheet


def save(session, sheet, action, correlation, operator="system", note=""):
    sheet.updated_at = now()
    project(sheet)
    row = session.get(ObjectRow, (sheet.dataset_id, "order_sheet", sheet.order_id))
    if row is None:
        row = ObjectRow(dataset_id=sheet.dataset_id, kind="order_sheet", id=sheet.order_id,
                        version=0, data={})
        session.add(row)
    else:
        sheet.version += 1
    row.version, row.data = sheet.version, sheet.model_dump(mode="json")
    audit(session, sheet.dataset_id, f"order.{action}", sheet.order_id, correlation,
          operator=operator, note=note, revision=sheet.revision, sheet=row.data)
    session.flush()
    return sheet


def create(session, body, correlation):
    if dataset(session, body.dataset_id).mode != "workspace":
        raise AppError(409, "WORKSPACE_REQUIRED", "Лист заказа создается в рабочей копии.")
    sheet = OrderSheet(**body.model_dump(), order_id=uid(), created_at=now(), updated_at=now())
    return save(session, sheet, "create", correlation)


def load(session, dataset_id, order_id, expected_version=None):
    return OrderSheet.model_validate(get_object(session, dataset_id, "order_sheet", order_id,
                                                expected_version).data)


def capture(session, sheet, services, quote_id=None, remnant_id=None):
    quote_id = quote_id or sheet.facts.quote.quote_id
    remnant_id = remnant_id or sheet.facts.remnant.remnant_id
    facts = OrderFacts.model_validate(source(services).capture(
        session, sheet.dataset_id, quote_id, remnant_id, sheet.order_id,
    ))
    if (facts.dataset_id != sheet.dataset_id or facts.quote.dataset_id != sheet.dataset_id
            or facts.remnant.dataset_id != sheet.dataset_id
            or facts.quote.quote_id != quote_id or facts.remnant.remnant_id != remnant_id):
        raise AppError(409, "ORDER_SOURCE_SCOPE", "Источник вернул факты другого заказа/набора.")
    require_quote_customer(facts, sheet.customer_ref)
    return facts


def usable(facts):
    return (facts.compatible and facts.quote.status in {"ready", "confirmed"}
            and not facts.quote.preliminary and facts.quote.total_tg is not None
            and facts.quote.material_mapping_status == "confirmed"
            and facts.quote.material_id == facts.remnant.material_id)


def same_reservation(reference, current):
    return reference.model_dump() == current.model_dump() and current.state == "active"


def recheck(session, sheet, services, correlation):
    if not sheet.facts or sheet.quote_state == "stale" or sheet.lifecycle != "open":
        return project(sheet)
    reason = None
    stale_code = "ORDER_STALE"
    try:
        current = capture(session, sheet, services)
        # Legacy snapshots without ownership cannot inherit a client's identity on read.
        require_quote_customer(sheet.facts, sheet.customer_ref)
        sheet.stale_conflicts = [
            f"quote:{current.quote.quote_id}:{current.quote.revision}",
            f"remnant:{current.remnant.remnant_id}:{current.remnant.version}:{current.remnant.status}",
            *[f"alternative:{rid}" for rid in current.alternative_remnant_ids],
        ]
        if canonical_hash(current.model_dump(mode="json")) != sheet.facts_hash:
            reason = "Изменились расчет, прайс, соответствие материала или складской источник."
        if sheet.reservation and sheet.reservation.state == "active":
            reservation = source(services).reservation(session, sheet.dataset_id,
                                                       sheet.reservation.reservation_id)
            if not same_reservation(sheet.reservation, reservation):
                reason = "Резерв изменен или больше не принадлежит этой ревизии заказа."
        elif current.remnant.status != "available":
            reason = "Кусок недоступен; требуется новый подбор."
    except AppError as exc:
        if exc.status not in {404, 409}:
            raise
        if exc.code in CUSTOMER_ERRORS:
            stale_code, reason = exc.code, CUSTOMER_ERRORS[exc.code]
            sheet.stale_conflicts = exc.conflicts
        else:
            reason = "Источник изменен или удален; требуется пересчет."
    if reason:
        sheet.quote_state, sheet.warehouse_state, sheet.stale_reason = "stale", "stale", reason
        sheet.stale_code = stale_code
        save(session, sheet, "stale", correlation)
    else:
        sheet.stale_conflicts = []
    return project(sheet)


def active_reservation(sheet):
    return sheet.reservation is not None and sheet.reservation.state == "active"


def apply(session, order_id, body, action, services, correlation):
    sheet = load(session, body.dataset_id, order_id, body.expected_version)
    if sheet.lifecycle != "open":
        raise AppError(409, "ORDER_CLOSED", "Заказ уже передан или отменен; история сохранена.")
    if action == "bind":
        if active_reservation(sheet):
            raise AppError(409, "RELEASE_REQUIRED", "Сначала явно снимите предыдущий резерв.")
        facts = capture(session, sheet, services, body.quote_id, body.remnant_id)
        if facts.quote.revision != body.quote_revision or facts.remnant.version != body.remnant_version:
            raise AppError(409, "SOURCE_VERSION_CONFLICT", "Расчет или кусок уже изменен.",
                           conflicts=[f"quote:{facts.quote.quote_id}:{facts.quote.revision}",
                                      f"remnant:{facts.remnant.remnant_id}:{facts.remnant.version}"])
        if not usable(facts) or facts.remnant.status != "available":
            raise AppError(409, "ORDER_FACTS_NOT_READY", "Расчет/совместимость/наличие требуют уточнения.",
                           conflicts=facts.alternative_remnant_ids)
        sheet.revision += 1
        sheet.facts, sheet.facts_hash = facts, canonical_hash(facts.model_dump(mode="json"))
        sheet.quote_state, sheet.warehouse_state = "draft", "unchecked"
        sheet.stale_reason, sheet.reservation, sheet.reminder_ids = None, None, []
        sheet.stale_code = None
        sheet.stale_conflicts = []
    elif action in {"release", "cancel"}:
        if active_reservation(sheet):
            released = source(services).release(session, sheet.reservation)
            if (released.state != "released" or released.reservation_id != sheet.reservation.reservation_id
                    or released.order_id != sheet.order_id or released.dataset_id != sheet.dataset_id):
                raise AppError(409, "RESERVATION_RELEASE_FAILED", "Источник не подтвердил снятие резерва.")
            sheet.reservation = released
        if action == "cancel":
            sheet.lifecycle = "cancelled"
        elif sheet.facts:
            sheet.quote_state, sheet.warehouse_state = "stale", "stale"
            sheet.stale_reason = "Резерв снят; повторно выберите актуальные факты."
            sheet.stale_code = "ORDER_STALE"
    else:
        sheet = recheck(session, sheet, services, correlation)
        if sheet.quote_state == "stale":
            # Return a durable stale transition; route raises conflict AFTER transaction commit.
            return {"sheet": sheet.model_dump(mode="json"), "conflict": sheet.stale_code or "ORDER_STALE"}
        if sheet.facts is None or not usable(sheet.facts):
            raise AppError(409, "ORDER_FACTS_REQUIRED", "Сначала привяжите проверенный расчет и кусок.")
        if action == "confirm":
            sheet.quote_state = "confirmed"
        elif action == "reserve":
            if sheet.quote_state != "confirmed":
                raise AppError(409, "CONFIRM_REQUIRED", "Сначала подтвердите расчет.")
            if not active_reservation(sheet):
                ref = source(services).reserve(session, sheet.facts, sheet.order_id, sheet.revision)
                if (ref.dataset_id != sheet.dataset_id or ref.order_id != sheet.order_id
                        or ref.order_revision != sheet.revision or ref.state != "active"
                        or ref.remnant_id != sheet.facts.remnant.remnant_id):
                    raise AppError(409, "RESERVATION_SCOPE", "Резерв не принадлежит этому заказу.")
                current = capture(session, sheet, services)
                # Only inventory version/status may change due to our own reservation.
                before = sheet.facts.model_dump(mode="json")
                after = current.model_dump(mode="json")
                for value in (before, after):
                    value["remnant"].pop("version")
                    value["remnant"].pop("status")
                if (before != after or not usable(current) or current.remnant.status != "reserved"
                        or current.remnant.version != ref.remnant_version):
                    raise AppError(409, "RESERVATION_FACTS_CHANGED", "Факты изменились во время резерва.")
                sheet.reservation, sheet.facts = ref, current
                sheet.facts_hash = canonical_hash(current.model_dump(mode="json"))
        elif action in {"warehouse-check", "handover"}:
            if not active_reservation(sheet) or sheet.quote_state != "confirmed":
                raise AppError(409, "RESERVATION_REQUIRED", "Нужны подтвержденный расчет и действующий резерв.")
            if action == "warehouse-check":
                if not body.note.strip():
                    raise AppError(422, "WAREHOUSE_NOTE_REQUIRED", "Запишите результат личной проверки склада.")
                sheet.warehouse_state = "checked"
            else:
                if sheet.warehouse_state != "checked":
                    raise AppError(409, "WAREHOUSE_CHECK_REQUIRED", "Сначала явно проверьте кусок на складе.")
                sheet.warehouse_state, sheet.lifecycle = "handed_over", "handed_over"
        elif action == "reminder":
            reminder = get_object(session, sheet.dataset_id, "reminder", body.reminder_id).data
            if (reminder["recipient_client_id"] != sheet.customer_ref
                    or reminder["subject_type"] != "quote_example"
                    or reminder["subject_ref"] != sheet.facts.quote.quote_id
                    or reminder["subject_version"] != sheet.facts.quote.revision
                    or reminder["state"] not in {"draft", "scheduled", "due"}):
                raise AppError(409, "REMINDER_ORDER_MISMATCH", "Задача относится к другому адресату/расчету.")
            sheet.reminder_ids = sorted(set([*sheet.reminder_ids, body.reminder_id]))
        else:
            raise AppError(422, "UNKNOWN_ORDER_ACTION", "Неизвестная команда листа заказа.")
    save(session, sheet, action, correlation, body.operator, body.note)
    return {"sheet": sheet.model_dump(mode="json")}


def history(session, dataset_id, order_id):
    load(session, dataset_id, order_id)
    return [OrderHistory(event_id=r.id, action=r.action, recorded_at=r.created_at,
                         operator=r.versions.get("operator", "system"), note=r.versions.get("note", ""),
                         sheet=OrderSheet.model_validate(r.versions["sheet"]))
            for r in session.scalars(select(AuditRow).where(
                AuditRow.dataset_id == dataset_id, AuditRow.object_id == order_id,
                AuditRow.action.like("order.%")).order_by(AuditRow.id))]
