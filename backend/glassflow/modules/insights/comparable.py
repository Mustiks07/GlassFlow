"""N08 comparable groups use the same organizer formulas as M1–M5."""

import re
from collections import defaultdict

from glassflow.contracts.insights import (
    AnalyticsAnswer,
    ComparableGroup,
    ComparableRequest,
    ComparableView,
    ComparableWarning,
)
from glassflow.modules.crm.service import metrics_from_records
from glassflow.modules.platform.imports import records

FIELDS = {"product_group": "группа_товара", "channel": "канал", "client_type": "тип_клиента"}
METRICS = {
    "mean_response_minutes": r"врем|ответ|скорост",
    "mean_sale_tg": r"чек|продан.*сумм",
    "returns": r"возврат|вернув",
    "conversion": r"конверс|дол.*продаж",
    "complaints": r"жалоб",
    "discounts": r"скидок|скидк",
    "application_count": r"сколько|количеств|число",
}


def manager_of(row):
    return row["manager"] if row["manager"] in {"M1", "M2", "M3", "M4", "M5"} else "unknown"


def compare(session, body):
    source = records(session, body.dataset_id, "applications")
    filters = {k: getattr(body, k) for k in [*FIELDS, "day_from", "day_to"]}
    selected = [
        r
        for r in source
        if manager_of(r.data) in body.managers
        and all(filters[k] is None or r.data[FIELDS[k]] == filters[k] for k in FIELDS)
        and (body.day_from is None or int(r.data["день_года"]) >= body.day_from)
        and (body.day_to is None or int(r.data["день_года"]) <= body.day_to)
    ]
    strata = defaultdict(list)
    for row in selected:
        strata[tuple(row.data[FIELDS[k]] for k in body.dimensions)].append(row)
    overall = [v for v in metrics_from_records(selected, {}) if v.manager in body.managers]
    groups = []
    for key in sorted(strata, key=lambda group: tuple((v is not None, str(v)) for v in group))[
        body.offset : body.offset + body.limit
    ]:
        rows = strata[key]
        values = [v for v in metrics_from_records(rows, {}) if v.manager in body.managers]
        warnings = []
        for manager in values:
            for metric, evidence in manager.evidence.items():
                count, total = evidence.denominator, evidence.total
                code = (
                    "NO_OBSERVATIONS" if count == 0 else "SMALL_GROUP" if count < body.minimum_count else None
                )
                if code:
                    warnings.append(
                        ComparableWarning(
                            manager=manager.manager,
                            metric=metric,
                            known_count=count,
                            total_count=total,
                            code=code,
                        )
                    )
                if count < total:
                    warnings.append(
                        ComparableWarning(
                            manager=manager.manager,
                            metric=metric,
                            known_count=count,
                            total_count=total,
                            code="INCOMPLETE",
                        )
                    )
        groups.append(
            ComparableGroup(
                dimensions=dict(zip(body.dimensions, key, strict=True)),
                application_count=len(rows),
                managers=values,
                warnings=warnings,
            )
        )
    return ComparableView(
        dataset_id=body.dataset_id,
        resolved=body,
        total_groups=len(strata),
        matched_application_count=len(selected),
        groups=groups,
        overall=overall,
    )


def answer(session, body):
    source = records(session, body.dataset_id, "applications")
    text = body.question.casefold().replace("ё", "е")
    if not re.search(r"сравн|покаж|сколько|како|у кого|доля|средн|аналит|чек|возврат|почему", text):
        return AnalyticsAnswer(
            status="clarification",
            answer_ru="Выберите показатель: число заявок, время ответа, конверсия, возвраты, средний чек, жалобы или скидки.",
        )
    metric_names = [
        name for name, pattern in METRICS.items() if name != "application_count" and re.search(pattern, text)
    ]
    if not metric_names and re.search(METRICS["application_count"], text):
        metric_names = ["application_count"]
    if len(metric_names) != 1:
        return AnalyticsAnswer(
            status="clarification",
            answer_ru="Какой один показатель сравнить: время ответа, средний чек, возвраты, конверсию, жалобы, скидки или число заявок?",
        )
    managers = sorted({f"M{x}" for x in re.findall(r"(?<!\w)[mм]([1-5])(?!\d)", text)}) or [
        "M1",
        "M2",
        "M3",
        "M4",
        "M5",
    ]
    filters = {}
    for field, column in FIELDS.items():
        candidates = {r.data[column] for r in source if isinstance(r.data[column], str) and r.data[column]}
        found = [v for v in candidates if v.casefold().replace("ё", "е") in text]
        if len(found) > 1:
            return AnalyticsAnswer(
                status="clarification",
                answer_ru=f"Уточните одну группу для сравнения: {', '.join(sorted(found))}.",
            )
        if found:
            filters[field] = found[0]
    dimensions = (
        ["channel"]
        if re.search(r"по канал|каналам", text)
        else ["client_type"]
        if "типам клиент" in text
        else ["product_group"]
    )
    query = ComparableRequest(dataset_id=body.dataset_id, managers=managers, dimensions=dimensions, **filters)
    value = compare(session, query)
    return AnalyticsAnswer(
        status="answered",
        metric=metric_names[0],
        resolved=query,
        comparison=value,
        answer_ru=f"Сравнение по одному показателю внутри сопоставимых групп; заявок: {value.matched_application_count}. Численности, известные знаменатели и пропуски приведены в таблице. Причинные выводы по этим данным делать нельзя.",
    )
