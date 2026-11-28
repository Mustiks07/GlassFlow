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

# A finite parser may narrow only by recognized source values. Unknown text is
# not discarded: it might be a date, a negation, a city, or another requested scope.
SAFE_WORDS = set("сравни сравните сравнить сравнение сравнения покажи покажите показать выведи выведите дай дайте "
    "сколько какое какая какой какие как у кого кого по в во на для от из с со до и или между всех все всем "
    "менеджер менеджера менеджеров менеджерам менеджеры менеджере группе группы групп группам товар товара "
    "товаров товарной товарным каналу канале каналы каналам канал каналов тип типу типам типа клиента "
    "клиентов средний среднее средняя среднюю средние чек чека чеки время времени ответа ответ ответов "
    "скорость скорости конверсия конверсии конверсию доля долю продаж продажи возврат возвраты возвратов "
    "вернувшихся жалобы жалоб жалобам скидки скидок скидкам заявка заявки заявок число количество "
    "заявкам заявке аналитика аналитику пожалуйста".split())


def clarify(text):
    return AnalyticsAnswer(status="clarification", answer_ru=text)


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
    explicit_managers = re.findall(r"(?<!\w)[mм]\s*(\d+)(?!\w)", text)
    if any(value not in {"1", "2", "3", "4", "5"} for value in explicit_managers):
        return clarify("Доступны менеджеры M1–M5. Уточните менеджера; неизвестное имя не заменяется всеми.")
    if re.search(r"почему|причин|влия[ею]|из-за", text):
        return clarify("По этим данным можно сравнить показатели и состав заявок, но нельзя установить причины. Какой показатель показать?")
    if not re.search(r"сравн|покаж|сколько|како|у кого|доля|средн|аналит|чек|возврат|почему", text):
        return AnalyticsAnswer(
            status="clarification",
            answer_ru="Выберите показатель: число заявок, время ответа, конверсия, возвраты, средний чек, жалобы или скидки.",
        )
    metric_names = [
        name for name, pattern in METRICS.items() if name != "application_count" and re.search(pattern, text)
    ]
    if metric_names and re.search(r"\b(?:число|количеств\w*)\b|сколько\s+заявок", text):
        metric_names.append("application_count")
    if not metric_names and re.search(METRICS["application_count"], text):
        metric_names = ["application_count"]
    if len(metric_names) != 1:
        return AnalyticsAnswer(
            status="clarification",
            answer_ru="Какой один показатель сравнить: время ответа, средний чек, возвраты, конверсию, жалобы, скидки или число заявок?",
        )
    managers = sorted({f"M{x}" for x in explicit_managers}) or [
        "M1",
        "M2",
        "M3",
        "M4",
        "M5",
    ]
    filters = {}
    residual = re.sub(r"(?<!\w)[mм]\s*[1-5](?!\w)", " ", text)
    for field, column in FIELDS.items():
        candidates = {r.data[column] for r in source if isinstance(r.data[column], str) and r.data[column]}
        spans = sorted([(match.start(), match.end(), value) for value in candidates
            for match in re.finditer(r"(?<!\w)" + re.escape(value.casefold().replace("ё", "е")) + r"(?!\w)", text)],
            key=lambda item: (item[0], item[0] - item[1]))
        found, end = [], -1
        for start, stop, value in spans:
            if start >= end:
                found.append(value)
                end = stop
        found = list(dict.fromkeys(found))
        if len(found) > 1:
            return AnalyticsAnswer(
                status="clarification",
                answer_ru=f"Уточните одну группу для сравнения: {', '.join(sorted(found))}.",
            )
        if found:
            filters[field] = found[0]
            residual = re.sub(r"(?<!\w)" + re.escape(found[0].casefold().replace("ё", "е")) + r"(?!\w)", " ", residual)
    tokens = re.findall(r"\w+", residual)
    unparsed = [token for token in tokens if token not in SAFE_WORDS]
    if unparsed:
        return clarify("Не могу применить указанное условие или период без уточнения: " +
                       ", ".join(dict.fromkeys(unparsed[:12])) +
                       ". Поддерживаются M1–M5 и точные значения группы товара, канала и типа клиента; период задайте явными границами дня года в фильтрах.")
    for field, marker in {"channel": r"\bканал[уеа]\b", "product_group": r"\bгрупп[еу]\b",
                           "client_type": r"\bтип[уеа] клиент"}.items():
        if field not in filters and re.search(marker, text):
            return clarify("Уточните точное значение фильтра или запросите сравнение по всем группам, каналам или типам клиентов.")
    dimensions = [field for field, marker in {"product_group": r"группам", "channel": r"каналам",
                  "client_type": r"типам клиент"}.items() if re.search(marker, text)] or ["product_group"]
    query = ComparableRequest(dataset_id=body.dataset_id, managers=managers, dimensions=dimensions, **filters)
    value = compare(session, query)
    return AnalyticsAnswer(
        status="answered",
        metric=metric_names[0],
        resolved=query,
        comparison=value,
        answer_ru=f"Сравнение по одному показателю внутри сопоставимых групп; заявок: {value.matched_application_count}. Численности, известные знаменатели и пропуски приведены в таблице. Причинные выводы по этим данным делать нельзя.",
    )
