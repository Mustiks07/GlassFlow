from collections import defaultdict
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select

from glassflow.contracts.crm import ManagerMetrics, RankedApplication, Ranking, Ratio, ReminderRequest
from glassflow.core.errors import AppError
from glassflow.core.models import ObjectRow, uid
from glassflow.core.uow import audit, canonical_hash, get_object
from glassflow.modules.platform.imports import LABEL, records

POLICY = "reference-v1"


def baseline_key(row):
    return (
        -int(row["прошлых_заявок"]),
        int(row["жалоба"]) if row.get("жалоба") is not None else 2,
        row["manager"] == "M4",
        int(row["дней_с_последнего_контакта"]),
    )


def rank_rows(rows, policy="reference"):
    if policy != "reference":
        raise AppError(409, "MODEL_NOT_PROMOTED", "Модель не доказала улучшение; зафиксирована reference-v1.")
    if len(rows) < 25:
        raise AppError(422, "INSUFFICIENT_APPLICATIONS", "Для конкурсного отбора нужны минимум 25 заявок.")
    selected = sorted(rows, key=baseline_key)[:25]
    grouped = defaultdict(list)
    ranked = []
    for position, row in enumerate(selected):
        grouped[row["client_id"]].append(row["app_id"])
        reasons = [
            f"Прошлых заявок: {row['прошлых_заявок']}",
            f"Жалоба: {row.get('жалоба') if row.get('жалоба') is not None else 'неизвестно (после известных значений при равных признаках)'}",
            f"Дней с контакта: {row['дней_с_последнего_контакта']}",
            "Стабильная сортировка; M4 - признак эталона, не причинная оценка менеджера",
        ]
        ranked.append(
            RankedApplication(
                app_id=row["app_id"],
                client_id=row["client_id"],
                priority=float(25 - position),
                reasons=reasons,
            )
        )
    known = [r for r in selected if r.get(LABEL) is not None]
    precision = sum(int(r[LABEL]) for r in known) / 25 if len(known) == 25 else None
    return Ranking(
        rows=ranked,
        unique_client_count=len(grouped),
        policy="reference",
        observed_precision=precision,
        grouped_clients=dict(grouped),
        policy_version=POLICY,
    )


def rank(session, dataset_id, policy="reference"):
    return rank_rows([r.data for r in records(session, dataset_id, "applications")], policy)


def metrics(session, dataset_id, filters):
    source = records(session, dataset_id, "applications")
    selected = []
    fields = {"product_group": "группа_товара", "channel": "канал", "client_type": "тип_клиента"}
    for record in source:
        row = record.data
        group = row["manager"] if row["manager"] in {"M1", "M2", "M3", "M4", "M5"} else "unknown"
        if filters.get("manager") and group != filters["manager"]:
            continue
        if any(filters.get(f) is not None and row[k] != filters[f] for f, k in fields.items()):
            continue
        if filters.get("day_from") is not None and int(row["день_года"]) < filters["day_from"]:
            continue
        if filters.get("day_to") is not None and int(row["день_года"]) > filters["day_to"]:
            continue
        selected.append((group, record))
    groups = [filters["manager"]] if filters.get("manager") else ["M1", "M2", "M3", "M4", "M5"]
    if any(g == "unknown" for g, _ in selected) and "unknown" not in groups:
        groups.append("unknown")
    output = []
    for group in groups:
        rows = [r for g, r in selected if g == group]
        evidence = {}

        def describe(name, known, numerator, definition):
            evidence[name] = {
                "numerator": str(numerator) if numerator is not None else None,
                "denominator": len(known),
                "source_app_ids": [r.public_id for r in rows],
                "known_app_ids": [r.public_id for r in known],
                "source_rows": [r.source_row for r in known],
                "total": len(rows),
                "completeness": len(known) / len(rows) if rows else None,
                "definition": definition,
            }

        def ratio(name, field):
            known = [r for r in rows if r.data.get(field) is not None]
            positive = sum(int(r.data[field]) for r in known)
            describe(name, known, positive, f"{field}=1 / известные {field}; исторические строки")
            return Ratio(
                numerator=positive, denominator=len(known), value=positive / len(known) if known else None
            )

        def mean(name, field, paid_only=False):
            known = [
                r
                for r in rows
                if r.data.get(field) is not None and (not paid_only or r.data.get("продано") == "1")
            ]
            total = sum((Decimal(r.data[field]) for r in known), Decimal(0))
            describe(
                name, known, total, f"Среднее {field}" + (" по продано=1" if paid_only else " по известным")
            )
            return total / len(known) if known else None

        describe("application_count", rows, len(rows), "Число исходных заявок после фильтра")
        response = mean("mean_response_minutes", "ответ_через_мин")
        sale, all_amount = mean("mean_sale_tg", "сумма_тг", True), mean("mean_application_tg", "сумма_тг")

        def money(v):
            return str(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if v is not None else None

        output.append(
            ManagerMetrics(
                manager=group,
                application_count=len(rows),
                mean_response_minutes=float(response) if response is not None else None,
                conversion=ratio("conversion", "продано"),
                returns=ratio("returns", LABEL),
                mean_sale_tg=money(sale),
                mean_application_tg=money(all_amount),
                complaints=ratio("complaints", "жалоба"),
                discounts=ratio("discounts", "скидка"),
                evidence=evidence,
                source_manager_values=sorted({r.data["manager"] for r in rows}),
            )
        )
    return output


def validate_recipient(session, body):
    rows = {r.public_id: r.data for r in records(session, body.dataset_id, "applications")}
    if not body.source_app_ids or len(set(body.source_app_ids)) != len(body.source_app_ids):
        raise AppError(422, "SOURCE_APPLICATIONS_REQUIRED", "Укажите разные исходные заявки адресата.")
    if any(a not in rows or rows[a]["client_id"] != body.recipient_client_id for a in body.source_app_ids):
        raise AppError(
            422, "RECIPIENT_MISMATCH", "Исходные заявки должны принадлежать адресату в этом наборе."
        )
    if not body.owner.strip():
        raise AppError(422, "OWNER_REQUIRED", "Укажите ответственного.")


def create_reminder(session, body, services, correlation):
    validate_recipient(session, body)
    check = services.check_subject(
        session,
        body.dataset_id,
        body.subject_type,
        body.subject_ref,
        body.subject_version,
        body.compatibility_ref,
        body.compatibility_version,
    )
    if not check["valid"]:
        raise AppError(409, "STALE_SUBJECT", "Предмет устарел или несовместим; выберите другой.")
    if body.subject_type != "interest" and check.get("version") is None:
        raise AppError(503, "SUBJECT_VERSION_MISSING", "Сервис не вернул проверяемую версию предмета.")
    period = body.active_period or (body.due_at[:10] if body.due_at else "unscheduled")
    unique = canonical_hash(
        [body.recipient_client_id, body.subject_type, (body.subject_ref or "").strip().casefold(), period]
    )
    active = session.scalars(
        select(ObjectRow).where(ObjectRow.dataset_id == body.dataset_id, ObjectRow.kind == "reminder")
    )
    for row in active:
        if row.data["unique"] == unique and row.data["state"] not in {"done", "cancelled"}:
            refresh_reminder(session, row, services, correlation)
            return reminder_dto(row)
    data = body.model_dump()
    data.update(
        state="draft",
        subject_version=check.get("version"),
        active_period=period,
        unique=unique,
        stale_reason=None,
    )
    row = ObjectRow(dataset_id=body.dataset_id, kind="reminder", id=uid(), version=0, data=data)
    session.add(row)
    audit(session, body.dataset_id, "reminder.create", row.id, correlation, after=0)
    return reminder_dto(row)


def reminder_dto(row):
    return {k: v for k, v in row.data.items() if k != "unique"} | {
        "reminder_id": row.id,
        "version": row.version,
    }


def refresh_reminder(session, row, services, correlation):
    data = dict(row.data)
    if data["state"] in {"done", "cancelled", "stale"}:
        return
    check = services.check_subject(
        session,
        row.dataset_id,
        data["subject_type"],
        data["subject_ref"],
        data["subject_version"],
        data.get("compatibility_ref"),
        data.get("compatibility_version"),
    )
    new_state = data["state"]
    if not check["valid"] or check.get("version") != data["subject_version"]:
        new_state = "stale"
        data["stale_reason"] = check.get("reason", "Предмет изменен или недоступен")
    elif (
        new_state == "scheduled"
        and data["due_at"]
        and datetime.fromisoformat(data["due_at"]) <= datetime.now(UTC)
    ):
        new_state = "due"
    if new_state != data["state"]:
        data["state"] = new_state
        row.version += 1
        row.data = data
        audit(session, row.dataset_id, "reminder.recheck", row.id, correlation, after=row.version)


def mutate_reminder(session, reminder_id, body, services, correlation, action):
    row = get_object(session, body.dataset_id, "reminder", reminder_id, body.expected_version)
    if action != "cancel":
        refresh_reminder(session, row, services, correlation)
    data = dict(row.data)
    if data["state"] == "stale" and action != "cancel":
        # Commit the stale marker even though confirmation is rejected.
        return {"_conflict": "STALE_SUBJECT", "reminder": reminder_dto(row)}
    if data["state"] in {"done", "cancelled"}:
        raise AppError(409, "REMINDER_CLOSED", "Закрытая задача не изменяется.")
    if action == "confirm":
        if not data["due_at"]:
            raise AppError(422, "DUE_AT_REQUIRED", "Укажите срок напоминания.")
        data["state"] = "due" if datetime.fromisoformat(data["due_at"]) <= datetime.now(UTC) else "scheduled"
    elif action == "cancel":
        data["state"] = "cancelled"
    else:
        for field in ("due_at", "owner", "text"):
            if field in body.model_fields_set:
                data[field] = getattr(body, field)
        from pydantic import ValidationError

        try:
            validated = ReminderRequest.model_validate(
                {k: v for k, v in data.items() if k in ReminderRequest.model_fields}
            )
        except ValidationError:
            raise AppError(422, "INVALID_REMINDER", "Проверьте срок, ответственного и поля задачи.") from None
        validate_recipient(session, validated)
        data.update(validated.model_dump())
        if data["state"] in {"scheduled", "due"}:
            data["state"] = (
                "draft"
                if not data["due_at"]
                else "due"
                if datetime.fromisoformat(data["due_at"]) <= datetime.now(UTC)
                else "scheduled"
            )
        if body.state == "done":
            data["state"] = "done"
    row.version += 1
    row.data = data
    audit(session, body.dataset_id, f"reminder.{action}", row.id, correlation, after=row.version)
    return reminder_dto(row)
