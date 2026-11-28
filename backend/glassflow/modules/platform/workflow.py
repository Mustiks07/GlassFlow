"""N06 read-only projection. Canonical aggregates remain the sole business state."""

from collections import Counter

from sqlalchemy import select

from glassflow.contracts.baskets import Basket, BasketReservation
from glassflow.contracts.labor import WorkflowItem, WorkflowQueue
from glassflow.contracts.orders import OrderSheet
from glassflow.core.errors import AppError
from glassflow.core.models import ObjectRow
from glassflow.core.uow import canonical_hash
from glassflow.modules.platform import baskets, orders
from glassflow.modules.platform.imports import dataset


def order_item(session, row, services):
    sheet = OrderSheet.model_validate(row.data)
    if sheet.lifecycle in {"completed", "cancelled"}:
        return None
    reason, role, action = "ORDER_QUOTE_REQUIRED", "manager", "Уточнить запрос и привязать расчет"
    amount = None
    if sheet.lifecycle == "handed_over":
        reason, role, action = "ACTUAL_USE_REQUIRED", "warehouse", "Сверить исполнение и подтвердить расход"
    elif sheet.quote_state == "stale":
        reason, action = sheet.stale_code or "ORDER_STALE", "Открыть измененные факты и перепривязать предложение"
    elif sheet.facts:
        try:
            current = orders.capture(session, sheet, services)
            stale = canonical_hash(current.model_dump(mode="json")) != sheet.facts_hash
            if sheet.reservation and sheet.reservation.state == "active":
                stale = stale or not orders.same_reservation(sheet.reservation, orders.source(services).reservation(
                    session, sheet.dataset_id, sheet.reservation.reservation_id))
            elif current.remnant.status != "available":
                stale = True
            if stale:
                reason, action = "ORDER_SOURCE_CHANGED", "Перечитать расчет/остаток и разрешить изменение"
            elif sheet.quote_state != "confirmed":
                reason, action, amount = "QUOTE_CONFIRM_REQUIRED", "Подтвердить проверенное предложение", current.quote.total_tg
            elif not orders.active_reservation(sheet):
                reason, action, amount = "RESERVATION_REQUIRED", "Повторно проверить и зарезервировать кусок", current.quote.total_tg
            elif sheet.warehouse_state == "unchecked":
                reason, role, action = "WAREHOUSE_CHECK_REQUIRED", "warehouse", "Лично сверить кусок и место"
            else:
                reason, role, action = "HANDOVER_REQUIRED", "warehouse", "Передать проверенное задание в работу"
        except AppError as exc:
            reason = exc.code
            role = "owner" if exc.status == 503 else "manager"
            action = "Восстановить подключение источника" if exc.status == 503 else "Разрешить конфликт источника"
    return WorkflowItem(subject_type="order", subject_id=row.id, version=row.version, reason_code=reason,
        responsible_role=role, next_action=action, route_hint=f"/#/workplace?order_id={row.id}",
        summary=sheet.request_text[:240], amount_tg=amount)


def basket_item(session, row, services):
    basket = Basket.model_validate(row.data)
    if basket.state in {"completed", "cancelled"}:
        return None
    state = basket.state
    reason = basket.stale_code or "BASKET_STALE"
    if basket.binding and basket.facts and state not in {"handed_over", "stale"}:
        try:
            current = baskets.capture(session, basket, basket.binding, services)
            if canonical_hash(current.model_dump(mode="json")) != basket.facts_hash:
                state, reason = "stale", "BASKET_SOURCE_CHANGED"
            if baskets.active(basket):
                current_reservation = BasketReservation.model_validate(baskets.source(services).reservation(
                    session, basket.dataset_id, basket.reservation.reservation_id))
                if current_reservation.model_dump() != basket.reservation.model_dump():
                    state, reason = "stale", "BASKET_RESERVATION_CHANGED"
        except AppError as exc:
            state, reason = "stale", exc.code
    choices = {
        "draft": ("BASKET_PARSE_REQUIRED", "manager", "Разобрать и проверить все строки заявки"),
        "needs_review": ("BASKET_CLARIFICATION_REQUIRED", "manager", "Уточнить неизвестные строки и проверить предупреждения"),
        "ready": ("BASKET_CONFIRM_REQUIRED", "manager", "Подтвердить всю корзину"),
        "confirmed": ("BASKET_RESERVATION_REQUIRED", "manager", "Проверить совместный подбор и зарезервировать"),
        "reserved": ("WAREHOUSE_CHECK_REQUIRED", "warehouse", "Лично проверить все зарезервированные куски"),
        "checked": ("HANDOVER_REQUIRED", "warehouse", "Передать корзину в работу"),
        "handed_over": ("ACTUAL_USE_REQUIRED", "warehouse", "Сверить детали и подтвердить фактический расход"),
        "stale": (reason, "manager", "Разрешить конфликт и перепроверить всю корзину"),
    }
    code, role, action = choices[state]
    if code.endswith("UNAVAILABLE"):
        role, action = "owner", "Восстановить подключение источника"
    return WorkflowItem(subject_type="basket", subject_id=row.id, version=row.version, reason_code=code,
        responsible_role=role, next_action=action, route_hint=f"/#/workplace?basket_id={row.id}",
        summary=basket.request_text[:240], amount_tg=basket.total_tg if state != "stale" else None)


def reminder_item(session, row, services):
    data = row.data
    if data["state"] in {"done", "cancelled"}:
        return None
    stale = data["state"] == "stale"
    reason = "REMINDER_STALE" if stale else "REMINDER_CONFIRM_REQUIRED" if data["state"] == "draft" else "REMINDER_FOLLOWUP"
    role = "manager"
    if not stale:
        try:
            check = services.check_subject(session, row.dataset_id, data["subject_type"], data.get("subject_ref"),
                data.get("subject_version"), data.get("compatibility_ref"), data.get("compatibility_version"))
            if not check["valid"]:
                stale, reason = True, "REMINDER_SUBJECT_CHANGED"
        except AppError as exc:
            stale, reason, role = True, exc.code, "owner" if exc.status == 503 else "manager"
    action = "Переподобрать актуальный предмет напоминания" if stale else (
        "Подтвердить срок и адресата" if data["state"] == "draft" else "Открыть локальную задачу в установленный срок")
    return WorkflowItem(subject_type="reminder", subject_id=row.id, version=row.version, reason_code=reason,
        responsible_role=role, next_action=action, route_hint=f"/#/clients?reminder_id={row.id}",
        summary=data.get("text") or data["subject_type"])


def queue(session, dataset_id, services):
    dataset(session, dataset_id)
    projection = {"order_sheet": order_item, "basket": basket_item, "reminder": reminder_item}
    items = []
    for row in session.scalars(select(ObjectRow).where(ObjectRow.dataset_id == dataset_id,
            ObjectRow.kind.in_(projection)).order_by(ObjectRow.kind, ObjectRow.id)):
        value = projection[row.kind](session, row, services)
        if value:
            items.append(value)
    return WorkflowQueue(dataset_id=dataset_id, items=items,
        counts=dict(Counter(item.reason_code for item in items))).model_dump(mode="json")
