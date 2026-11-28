"""U04 aggregate state machine. No pricing, NLP or stock geometry lives here."""

import json
from decimal import Decimal

from sqlalchemy import select

from glassflow.contracts.baskets import (
    Basket,
    BasketFacts,
    BasketHistory,
    BasketParseResult,
    BasketReservation,
)
from glassflow.core.errors import AppError
from glassflow.core.jobs import enqueue, get_job, job_dto
from glassflow.core.models import AuditRow, ObjectRow, SourceRow, now, uid
from glassflow.core.uow import audit, canonical_hash, get_object
from glassflow.modules.platform.imports import dataset
from glassflow.modules.platform.kb import kb_head
from glassflow.modules.platform.orders import require_quote_customer
from glassflow.modules.platform.system import get_settings

CLOSED = {"handed_over", "completed", "cancelled"}


def input_hash(basket):
    return canonical_hash({"customer_ref": basket.customer_ref, "request_text": basket.request_text,
                           "lines": [line.model_dump(mode="json") for line in basket.lines]})


def source(services):
    if services.basket_source is None:
        raise AppError(503, "BASKET_SOURCE_UNAVAILABLE", "Расчеты строк и совместный складской подбор не подключены.")
    return services.basket_source


def check_lines(basket, lines):
    ids = [line.line_id for line in lines]
    if len(ids) != len(set(ids)):
        raise AppError(422, "DUPLICATE_BASKET_LINE", "ID строк корзины должны быть уникальны.")
    for line in lines:
        if line.request and (line.request.dataset_id != basket.dataset_id or
                line.request.customer_id not in {None, basket.customer_ref}):
            raise AppError(409, "BASKET_REQUEST_SCOPE", "Строка относится к другому набору или клиенту.")


def save(session, basket, action, correlation, operator="system", note=""):
    basket.updated_at = now()
    row = session.get(ObjectRow, (basket.dataset_id, "basket", basket.basket_id))
    if row is None:
        row = ObjectRow(dataset_id=basket.dataset_id, kind="basket", id=basket.basket_id, version=0, data={})
        session.add(row)
    else:
        basket.version += 1
    row.version, row.data = basket.version, basket.model_dump(mode="json")
    audit(session, basket.dataset_id, f"basket.{action}", basket.basket_id, correlation,
          operator=operator, note=note, basket=row.data)
    session.flush()
    return basket


def load(session, dataset_id, basket_id, expected_version=None):
    data = get_object(session, dataset_id, "basket", basket_id, expected_version).data
    basket = Basket.model_validate(data)
    if ("review_warnings" not in data and basket.state == "needs_review"
            and basket.facts is None and basket.issues):
        basket.review_warnings = list(basket.issues)  # Preserve pre-field parser warnings until explicit review.
    return basket


def create(session, body, correlation):
    if dataset(session, body.dataset_id).mode != "workspace":
        raise AppError(409, "WORKSPACE_REQUIRED", "Корзина создается в рабочей копии.")
    basket = Basket(**body.model_dump(), basket_id=uid(), input_hash="pending", created_at=now(), updated_at=now())
    check_lines(basket, basket.lines)
    basket.input_hash = input_hash(basket)
    if any(line.clarification or line.request is None for line in basket.lines):
        basket.state = "needs_review"
    return save(session, basket, "create", correlation)


def active(basket):
    return basket.reservation is not None and basket.reservation.state == "active"


def replace_lines(session, basket, lines, correlation, operator, note, warnings=None):
    if basket.state in CLOSED or active(basket):
        raise AppError(409, "BASKET_EDIT_BLOCKED", "Сначала снимите резерв; переданная корзина не редактируется.")
    if warnings is None and basket.review_warnings and not note.strip():
        raise AppError(422, "BASKET_REVIEW_NOTE_REQUIRED", "Запишите результат явной проверки предупреждений разбора.")
    check_lines(basket, lines)
    basket.lines, basket.revision = lines, basket.revision + 1
    basket.input_hash = input_hash(basket)
    basket.binding = basket.facts = basket.facts_hash = basket.reservation = None
    basket.total_tg = basket.known_subtotal_tg = None
    basket.stale_code, basket.issues = None, warnings or []
    basket.review_warnings = list(warnings or [])
    basket.state = "needs_review" if basket.issues or any(line.clarification or line.request is None for line in lines) else "draft"
    return save(session, basket, "lines", correlation, operator, note)


def capture(session, basket, binding, services, *, initial=False):
    facts = BasketFacts.model_validate(source(services).capture(
        session, basket.model_copy(deep=True), binding.model_copy(deep=True))).model_copy(deep=True)
    ids = [line.line_id for line in basket.lines]
    refs = {line.line_id: line for line in binding.lines}
    current = {line.line_id: line for line in facts.lines}
    if (not ids or len(refs) != len(binding.lines) or len(current) != len(facts.lines)
            or set(ids) != set(refs) or set(ids) != set(current)
            or facts.dataset_id != basket.dataset_id or facts.basket_id != basket.basket_id
            or facts.input_hash != basket.input_hash or basket.input_hash != input_hash(basket)):
        raise AppError(409, "BASKET_FACTS_SCOPE", "Факты не покрывают весь текущий состав корзины.")
    glass = set()
    for draft in basket.lines:
        line, ref = current[draft.line_id], refs[draft.line_id]
        if line.kind == "glass":
            glass.add(line.line_id)
        if line.quote is None:
            if ref.quote_id is not None:
                raise AppError(409, "BASKET_QUOTE_MISSING", "Выбранный расчет отсутствует.")
            continue
        if (line.quote.dataset_id != basket.dataset_id or line.quote.quote_id != ref.quote_id
                or draft.request is None or line.source_request_hash != canonical_hash(draft.request.model_dump(mode="json"))):
            raise AppError(409, "BASKET_REQUEST_MISMATCH", "Расчет не соответствует сохраненным параметрам строки.")
        require_quote_customer(line, basket.customer_ref)
        if initial and line.quote.revision != ref.quote_revision:
            raise AppError(409, "QUOTE_VERSION_CONFLICT", "Версия расчета изменилась.")
    if facts.stock:
        stock = facts.stock
        if (stock.dataset_id != basket.dataset_id or stock.basket_id != basket.basket_id
                or stock.input_hash != basket.input_hash or not glass
                or len(stock.line_ids) != len(set(stock.line_ids)) or set(stock.line_ids) != glass
                or stock.selection_ref != binding.selection_ref):
            raise AppError(409, "BASKET_STOCK_SCOPE", "Совместный план должен покрывать все стеклянные строки.")
        if initial and stock.selection_version != binding.selection_version:
            raise AppError(409, "SELECTION_VERSION_CONFLICT", "Совместный план изменился.")
    elif binding.selection_ref is not None:
        raise AppError(409, "BASKET_SELECTION_MISSING", "Выбранный совместный план отсутствует.")
    return facts


def readiness(basket, facts):
    issues, known = list(basket.review_warnings), []
    current = {line.line_id: line for line in facts.lines}
    for draft in basket.lines:
        line = current[draft.line_id]
        quote = line.quote
        if quote and quote.total_tg is not None:
            known.append(Decimal(quote.total_tg))  # C3 already accounts for quantity/processing.
        if (draft.request is None or draft.clarification or line.clarification or quote is None
                or line.kind == "unresolved" or quote.total_tg is None
                or quote.status not in {"ready", "confirmed"} or quote.preliminary
                or line.compatibility == "needs_review"):
            issues.append(f"line:{draft.line_id}:needs_review")
        if line.kind == "glass" and (quote is None or quote.material_mapping_status != "confirmed"
                or not quote.material_id or draft.request is None or draft.request.dimensions is None):
            issues.append(f"line:{draft.line_id}:glass_parameters_required")
    if any(line.kind == "glass" for line in facts.lines) and (facts.stock is None or not facts.stock.validated):
        issues.append("joint_stock_validation_required")
    subtotal = format(sum(known, Decimal(0)), "f") if known else None
    return issues, subtotal if not issues else None, subtotal


def recheck(session, basket, services, correlation):
    if basket.state in CLOSED or basket.state == "stale" or not basket.binding or not basket.facts:
        return basket
    code, reason = None, None
    try:
        current = capture(session, basket, basket.binding, services)
        if canonical_hash(current.model_dump(mode="json")) != basket.facts_hash:
            code, reason = "BASKET_STALE", "Изменились расчет, прайс, совместный план или склад."
        if active(basket):
            ref = BasketReservation.model_validate(source(services).reservation(session, basket.dataset_id, basket.reservation.reservation_id)).model_copy(deep=True)
            if ref != basket.reservation or ref.state != "active":
                code, reason = "BASKET_RESERVATION_STALE", "Совместный резерв изменился."
    except AppError as exc:
        if exc.status not in {404, 409}:
            raise
        code, reason = exc.code, exc.message
    if reason:
        basket.state, basket.stale_code, basket.issues, basket.total_tg = "stale", code, [reason], None
        save(session, basket, "stale", correlation)
    return basket


def apply(session, basket_id, body, action, services, correlation):
    basket = load(session, body.dataset_id, basket_id, body.expected_version)
    if basket.state in CLOSED:
        raise AppError(409, "BASKET_CLOSED", "Корзина уже передана, завершена или отменена.")
    if action == "lines":
        return {"basket": replace_lines(session, basket, body.lines, correlation, body.operator, body.note).model_dump(mode="json")}
    if action == "bind":
        if active(basket):
            raise AppError(409, "RELEASE_REQUIRED", "Сначала снимите весь предыдущий резерв.")
        facts = capture(session, basket, body, services, initial=True)
        basket.issues, basket.total_tg, basket.known_subtotal_tg = readiness(basket, facts)
        basket.state = "needs_review" if basket.issues else "ready"
        basket.binding, basket.facts = body, facts
        basket.reservation = None
        basket.facts_hash, basket.stale_code = canonical_hash(facts.model_dump(mode="json")), None
        basket.revision += 1
    elif action in {"release", "cancel"}:
        if active(basket):
            current = BasketReservation.model_validate(source(services).reservation(session, basket.dataset_id, basket.reservation.reservation_id)).model_copy(deep=True)
            if current != basket.reservation:
                raise AppError(409, "BASKET_RESERVATION_STALE", "Нельзя снять измененный или чужой резерв.")
            released = BasketReservation.model_validate(source(services).release(session, current.model_copy(deep=True))).model_copy(deep=True)
            before, after = current.model_dump(), released.model_dump()
            for value in (before, after):
                value.pop("state")
                value.pop("remnant_versions")
            if before != after or released.state != "released":
                raise AppError(409, "BASKET_RELEASE_INVALID", "Источник не подтвердил снятие всего резерва.")
            basket.reservation = released
        basket.state, basket.total_tg = ("cancelled" if action == "cancel" else "stale"), None
        basket.stale_code, basket.issues = "RELEASED", ["Корзина требует новой привязки после снятия резерва."]
    else:
        recheck(session, basket, services, correlation)
        if basket.state == "stale":
            return {"basket": basket.model_dump(mode="json"), "conflict": basket.stale_code or "BASKET_STALE"}
        if action == "confirm":
            if basket.state == "confirmed":
                return {"basket": basket.model_dump(mode="json")}
            if basket.state != "ready" or basket.total_tg is None:
                raise AppError(409, "BASKET_NOT_READY", "Подтвердить можно только всю проверенную корзину.")
            basket.state = "confirmed"
        elif action == "reserve":
            if basket.state == "reserved":
                return {"basket": basket.model_dump(mode="json")}
            if basket.state != "confirmed":
                raise AppError(409, "BASKET_CONFIRM_REQUIRED", "Сначала подтвердите всю корзину.")
            if basket.facts.stock:
                ref = BasketReservation.model_validate(source(services).reserve(session, basket.model_copy(deep=True))).model_copy(deep=True)
                stock = basket.facts.stock
                if (ref.dataset_id != basket.dataset_id or ref.basket_id != basket.basket_id
                        or ref.basket_revision != basket.revision or ref.state != "active"
                        or (ref.selection_ref, ref.selection_version) != (stock.selection_ref, stock.selection_version)
                        or set(ref.remnant_versions) != set(stock.remnant_versions)):
                    raise AppError(409, "BASKET_RESERVATION_SCOPE", "Резерв не покрывает весь выбранный план.")
                current = capture(session, basket, basket.binding, services)
                before, after = basket.facts.model_dump(mode="json"), current.model_dump(mode="json")
                if after.get("stock") is None:
                    raise AppError(409, "BASKET_RESERVATION_FACTS", "План исчез во время резерва.")
                before["stock"].pop("remnant_versions")
                after["stock"].pop("remnant_versions")
                if before != after or current.stock.remnant_versions != ref.remnant_versions:
                    raise AppError(409, "BASKET_RESERVATION_FACTS", "Факты изменились во время резерва.")
                basket.reservation, basket.facts = ref, current
                basket.facts_hash = canonical_hash(current.model_dump(mode="json"))
            basket.state = "reserved"
        elif action == "warehouse-check":
            if basket.state != "reserved" or not body.note.strip():
                raise AppError(409, "BASKET_CHECK_REQUIRED", "Нужен резерв всей корзины и заметка личной проверки.")
            basket.state = "checked"
        elif action == "handover":
            if basket.state != "checked":
                raise AppError(409, "BASKET_CHECK_REQUIRED", "Сначала проверьте все позиции на складе.")
            basket.state = "handed_over"
        else:
            raise AppError(422, "UNKNOWN_BASKET_ACTION", "Неизвестная команда корзины.")
    save(session, basket, action, correlation, body.operator, body.note)
    return {"basket": basket.model_dump(mode="json")}


def parse_job(session, basket, body, handlers, correlation):
    import base64
    handler = handlers.get("basket.parse")
    if handler is None or handler.lane != "network":
        raise AppError(503, "BASKET_PARSER_UNAVAILABLE", "C3 parser worker пока не подключен.")
    if basket.state in CLOSED or active(basket):
        raise AppError(409, "BASKET_EDIT_BLOCKED", "Корзину с резервом или передачей нельзя заменить разбором.")
    head = kb_head(session, basket.dataset_id)
    document = session.scalar(select(SourceRow).where(SourceRow.dataset_id == basket.dataset_id, SourceRow.sha256 == head["sha256"]))
    settings = get_settings(session, {})
    job = enqueue(session, basket.dataset_id, "basket.parse", {
        "dataset_id": basket.dataset_id, "basket_id": basket.basket_id, "basket_version": basket.version,
        "input_hash": basket.input_hash, "customer_ref": basket.customer_ref, "request_text": basket.request_text,
        "existing_lines": [line.model_dump(mode="json") for line in basket.lines], "kb_version": head["kb_version"],
        "kb": json.loads(document.content), "ai_profile": settings.profile,
        "kb_bytes_b64": base64.b64encode(document.content).decode("ascii"),
        "ai_settings": settings.model_dump(exclude={"secret_present"}),
    })
    session.flush()
    audit(session, basket.dataset_id, "basket.parse_submitted", basket.basket_id, correlation,
          operator=body.operator, note=body.note, job_id=job.id, basket=basket.model_dump(mode="json"))
    return job_dto(job).model_dump(mode="json")


def apply_parse(session, basket, body, correlation):
    job = get_job(session, body.job_id, basket.dataset_id)
    if job.kind != "basket.parse" or job.state != "completed" or not job.result:
        raise AppError(409, "BASKET_PARSE_NOT_READY", "Нет завершенного результата parser.")
    result = BasketParseResult.model_validate(job.result)
    expected = (basket.dataset_id, basket.basket_id, basket.version, basket.input_hash)
    if ((result.dataset_id, result.basket_id, result.basket_version, result.input_hash) != expected
            or tuple(job.input.get(k) for k in ("dataset_id", "basket_id", "basket_version", "input_hash")) != expected):
        raise AppError(409, "BASKET_PARSE_STALE", "Разбор относится к другому или измененному входу.")
    return replace_lines(session, basket, result.lines, correlation, body.operator, body.note, result.warnings)


def history(session, dataset_id, basket_id):
    load(session, dataset_id, basket_id)
    return [BasketHistory(event_id=r.id, action=r.action, recorded_at=r.created_at,
                          operator=r.versions.get("operator", "system"), note=r.versions.get("note", ""),
                          basket=r.versions["basket"])
            for r in session.scalars(select(AuditRow).where(AuditRow.dataset_id == dataset_id,
                AuditRow.object_id == basket_id, AuditRow.action.like("basket.%")).order_by(AuditRow.id))]
