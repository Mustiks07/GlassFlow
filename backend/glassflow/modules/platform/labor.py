"""N05 durable human measurement protocol. No synthetic labor is inferred."""

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from statistics import median

from sqlalchemy import select

from glassflow.contracts.economics import LaborStudy
from glassflow.contracts.labor import LaborStudyExport, LaborStudyView
from glassflow.core.errors import AppError
from glassflow.core.models import ObjectRow, uid
from glassflow.core.uow import audit, canonical_hash, get_object
from glassflow.modules.platform.imports import dataset

PROCESS_EPOCH = uid()


def moment():
    return datetime.now(UTC)


def seconds(start, end):
    value = Decimal(str((end - datetime.fromisoformat(start)).total_seconds()))
    if value < 0:
        raise AppError(409, "CLOCK_MOVED_BACKWARDS", "Часы изменились назад; интервал требует проверки.")
    return value


def scalar(value):
    return format(Decimal(value).quantize(Decimal("0.001")), "f")


def workspace(session, dataset_id):
    if dataset(session, dataset_id).mode != "workspace":
        raise AppError(409, "WORKSPACE_REQUIRED", "Измерения собираются в рабочей копии.")


def event(measurement, action, when, operator, note="", **details):
    events = measurement["events"]
    value = {"action": action, "at": when.isoformat(), "operator": operator, "note": note,
             "details": details, "previous_hash": events[-1]["event_hash"] if events else None}
    events.append(value | {"event_hash": canonical_hash(value)})


def projected(measurement, when):
    result = deepcopy(measurement)
    interrupted = result.get("process_epoch") != PROCESS_EPOCH and result["state"] == "running"
    result["interruption_detected"] = result["interruption_detected"] or interrupted
    end = datetime.fromisoformat(result["finished_at"]) if result["finished_at"] else when
    result["elapsed_seconds"] = scalar(seconds(result["started_at"], end))
    if result["state"] == "running" and not interrupted:
        result["recorded_running_seconds"] = scalar(
            Decimal(result["recorded_running_seconds"]) + seconds(result["running_since"], when))
    for name in ("process_epoch", "running_since"):
        result.pop(name, None)
    return result


def pair_rows(study):
    groups = {}
    for item in study["measurements"]:
        groups.setdefault(item["pair_id"], []).append(item)
    pairs = []
    for pair_id, values in groups.items():
        methods = {m["method"]: m for m in values}
        reason = None
        if len(values) != 2 or set(methods) != {"manual", "app"}:
            reason = "PAIR_INCOMPLETE"
        elif len({(m["task_id"], m["task_input_ref"], m["input_hash"], m["operator"], m["planned_order"])
                  for m in values}) != 1:
            reason = "PAIR_INPUT_MISMATCH"
        elif any(m["state"] != "attested" or not m["human_confirmed"] for m in values):
            reason = "HUMAN_ATTESTATION_REQUIRED"
        saved = (scalar(Decimal(methods["manual"]["attested_active_seconds"])
                        - Decimal(methods["app"]["attested_active_seconds"])) if reason is None else None)
        pairs.append({"pair_id": pair_id, "task_id": values[0]["task_id"], "ready": reason is None,
                      "reason_code": reason, "saved_active_seconds": saved})
    return pairs


def view(row):
    data = deepcopy(row.data)
    data["measurements"] = [projected(m, moment()) for m in data["measurements"]]
    pairs = pair_rows(data)
    ready = [p for p in pairs if p["ready"]]
    return LaborStudyView(**data, study_id=row.id, version=row.version, pairs=pairs,
                          ready_pair_count=len(ready), export_ready=len(ready) >= 10
                          and len({p["task_id"] for p in ready}) == len(ready)).model_dump(mode="json")


def create(session, body, correlation):
    workspace(session, body.dataset_id)
    row = ObjectRow(dataset_id=body.dataset_id, kind="labor_study", id=uid(), version=0,
                    data=body.model_dump() | {"created_at": moment().isoformat(), "measurements": []})
    session.add(row)
    audit(session, body.dataset_id, "labor.create", row.id, correlation, after=0)
    return view(row)


def list_studies(session, dataset_id):
    dataset(session, dataset_id)
    return [view(r) for r in session.scalars(select(ObjectRow).where(
        ObjectRow.dataset_id == dataset_id, ObjectRow.kind == "labor_study").order_by(ObjectRow.id))]


def start(session, study_id, body, correlation):
    workspace(session, body.dataset_id)
    row = get_object(session, body.dataset_id, "labor_study", study_id, body.expected_version)
    data = deepcopy(row.data)
    previous = [m for m in data["measurements"] if m["pair_id"] == body.pair_id]
    if any(m["method"] == body.method for m in previous):
        raise AppError(409, "MEASUREMENT_EXISTS", "Способ этой пары уже записан; исходные измерения не заменяются.")
    if previous:
        first = previous[0]
        fields = ("task_id", "task_input_ref", "input_hash", "operator", "planned_order")
        if any(first[f] != getattr(body, f) for f in fields):
            raise AppError(409, "PAIR_INPUT_MISMATCH", "Оба способа требуют одной задачи, входов и оператора.")
        if first["state"] not in {"finished", "attested"}:
            raise AppError(409, "PAIR_OVERLAP", "Сначала завершите первый способ этой пары.")
    elif body.method != ("manual" if body.planned_order == "manual_first" else "app"):
        raise AppError(409, "PAIR_ORDER_MISMATCH", "Начните с запланированного первого способа.")
    when = moment()
    item = {k: v for k, v in body.model_dump().items() if k not in {"dataset_id", "expected_version"}}
    item.update(measurement_id=uid(), state="running", started_at=when.isoformat(), finished_at=None,
                running_since=when.isoformat(), process_epoch=PROCESS_EPOCH, recorded_running_seconds="0",
                elapsed_seconds="0", attested_active_seconds=None, attested_by=None, human_confirmed=False,
                result_ref=None, error_count=0, rework_seconds="0", interruption_detected=False,
                interruption_acknowledged=False, events=[])
    event(item, "start", when, body.operator)
    data["measurements"].append(item)
    save(session, row, data, "start", correlation, body.operator)
    return view(row)


def save(session, row, data, action, correlation, operator):
    before = row.version
    row.version += 1
    row.data = data
    audit(session, row.dataset_id, f"labor.{action}", row.id, correlation,
          before=before, after=row.version, operator=operator)


def act(session, study_id, measurement_id, body, action, correlation):
    workspace(session, body.dataset_id)
    row = get_object(session, body.dataset_id, "labor_study", study_id, body.expected_version)
    data = deepcopy(row.data)
    item = next((m for m in data["measurements"] if m["measurement_id"] == measurement_id), None)
    if item is None:
        raise AppError(404, "MEASUREMENT_NOT_FOUND", "Измерение не найдено в этом исследовании.")
    if item["operator"] != body.operator:
        raise AppError(409, "MEASUREMENT_OPERATOR_MISMATCH", "Действие подтверждает оператор измерения.")
    when = moment()
    if item["state"] == "attested":
        raise AppError(409, "MEASUREMENT_IMMUTABLE", "Подтвержденное измерение и его история неизменяемы.")
    if item["state"] == "running" and item["process_epoch"] != PROCESS_EPOCH:
        item["interruption_detected"] = True
        if not body.acknowledge_interruption or not body.note.strip():
            raise AppError(409, "INTERRUPTION_ACK_REQUIRED", "После перезапуска явно подтвердите разрыв и заметку.")
        item["interruption_acknowledged"] = True
        item["running_since"] = when.isoformat()
        item["process_epoch"] = PROCESS_EPOCH
        event(item, "interruption_acknowledged", when, body.operator, body.note)
    if action == "pause":
        if item["state"] != "running":
            raise AppError(409, "MEASUREMENT_NOT_RUNNING", "Приостановить можно текущее измерение.")
        item["recorded_running_seconds"] = scalar(Decimal(item["recorded_running_seconds"])
                                                  + seconds(item["running_since"], when))
        item["state"] = "paused"
    elif action == "resume":
        if item["state"] != "paused":
            raise AppError(409, "MEASUREMENT_NOT_PAUSED", "Продолжить можно приостановленное измерение.")
        item.update(state="running", running_since=when.isoformat(), process_epoch=PROCESS_EPOCH)
    elif action == "finish":
        if item["state"] not in {"running", "paused"}:
            raise AppError(409, "MEASUREMENT_FINISHED", "Измерение уже завершено.")
        elapsed = seconds(item["started_at"], when)
        if elapsed <= 0 or Decimal(body.rework_seconds) > elapsed:
            raise AppError(409, "MEASUREMENT_TIME_INVALID", "Нужен положительный интервал; переделки входят в него.")
        if item["state"] == "running":
            item["recorded_running_seconds"] = scalar(Decimal(item["recorded_running_seconds"])
                                                      + seconds(item["running_since"], when))
        item.update(state="finished", finished_at=when.isoformat(), elapsed_seconds=scalar(elapsed),
                    result_ref=body.result_ref, error_count=body.error_count, rework_seconds=body.rework_seconds)
    elif action == "attest":
        if item["state"] != "finished":
            raise AppError(409, "MEASUREMENT_NOT_FINISHED", "Сначала завершите интервал и запишите результат.")
        active = Decimal(body.active_seconds)
        if not 0 < active <= Decimal(item["elapsed_seconds"]) or Decimal(item["rework_seconds"]) > active:
            raise AppError(409, "ACTIVE_TIME_INVALID", "Активное время положительно, не больше прошедшего; переделки внутри.")
        item.update(state="attested", attested_active_seconds=body.active_seconds, human_confirmed=True,
                    attested_by=body.operator)
    else:
        raise AppError(422, "UNKNOWN_MEASUREMENT_ACTION", "Неизвестное действие измерения.")
    event(item, action, when, body.operator, body.note)
    save(session, row, data, action, correlation, body.operator)
    return view(row)


def export(session, dataset_id, study_id):
    row = get_object(session, dataset_id, "labor_study", study_id)
    data = row.data
    pairs = pair_rows(data)
    if any(not p["ready"] for p in pairs) or len(pairs) < 10 or len({p["task_id"] for p in pairs}) != len(pairs):
        raise AppError(409, "TEN_HUMAN_PAIRS_REQUIRED", "Для U07 нужны минимум десять разных полных подтвержденных пар.",
                       conflicts=[f"{p['pair_id']}:{p['reason_code']}" for p in pairs if not p["ready"]])
    studies = []
    for pair in pairs:
        values = {m["method"]: m for m in data["measurements"] if m["pair_id"] == pair["pair_id"]}
        manual, app = values["manual"], values["app"]
        studies.append(LaborStudy(task_id=pair["task_id"], protocol=data["protocol"], observer=data["observer"],
            operator=manual["operator"], measured_at=max(manual["finished_at"], app["finished_at"]),
            start_definition=data["start_definition"], end_definition=data["end_definition"],
            task_input_ref=f"{manual['task_input_ref']}#sha256={manual['input_hash']}",
            manual_result_ref=manual["result_ref"], app_result_ref=app["result_ref"],
            manual_started_at=manual["started_at"], manual_finished_at=manual["finished_at"],
            app_started_at=app["started_at"], app_finished_at=app["finished_at"],
            manual_active_seconds=manual["attested_active_seconds"], app_active_seconds=app["attested_active_seconds"],
            manual_error_count=manual["error_count"], app_error_count=app["error_count"],
            manual_rework_seconds=manual["rework_seconds"], app_rework_seconds=app["rework_seconds"]))
    savings = [Decimal(p["saved_active_seconds"]) for p in pairs]
    return LaborStudyExport(study_id=row.id, study_version=row.version, labor_studies=studies,
        pair_count=len(pairs), negative_saving_pairs=sum(s < 0 for s in savings),
        median_saved_active_seconds=scalar(median(savings)),
        source_ref=f"labor-study:{row.id}:v{row.version}").model_dump(mode="json")
