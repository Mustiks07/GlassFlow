"""Bounded untrusted upload parser; original bytes survive parsing unchanged."""

import base64
import csv
import hashlib
import io
import json
import re
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath

from sqlalchemy import select

from glassflow.contracts.platform import Dataset
from glassflow.core.errors import AppError
from glassflow.core.models import DatasetRow, RecordRow, SettingsRow, SourceRow, StagingRow, uid
from glassflow.core.uow import audit, canonical_hash

SCHEMAS = {
    "materials": "material_id,название,толщина_мм,цена_нового_стекла_тг_за_м2,закалённое".split(","),
    "stock": "remnant_id,material_id,длина_мм,ширина_мм,возраст_дней,дефект,место".split(","),
    "orders": "order_id,part_id,material_id,длина_мм,ширина_мм,премиум,тип_изделия".split(","),
    "questions": ["id", "question"],
    "dialogs": ["id", "client", "manager"],
    "applications": (
        "app_id,client_id,день_года,manager,группа_товара,сумма_тг,канал,тип_клиента,"
        "прошлых_заявок,дней_с_последнего_контакта,жалоба,доставка,скидка,"
        "ответ_через_мин,продано"
    ).split(","),
}
LABEL = "вернулся_за_60_дней"
LIMIT = 50 * 1024 * 1024
ROW_LIMIT = 100_000
OPTIONAL = {"ответ_через_мин", "продано", "жалоба", "доставка", "скидка", LABEL, "сумма_тг"}
FLAGS = {"закалённое", "дефект", "премиум", "жалоба", "доставка", "скидка", "продано", LABEL}
INTEGERS = {
    "толщина_мм",
    "длина_мм",
    "ширина_мм",
    "возраст_дней",
    "день_года",
    "прошлых_заявок",
    "дней_с_последнего_контакта",
    "ответ_через_мин",
}
POSITIVE = {"толщина_мм", "длина_мм", "ширина_мм"}
MONEY = {"цена_нового_стекла_тг_за_м2", "сумма_тг"}


def dataset(session, dataset_id):
    row = session.get(DatasetRow, dataset_id)
    if row is None:
        raise AppError(404, "DATASET_NOT_FOUND", "Набор не найден.")
    return row


def dataset_dto(row):
    from sqlalchemy.orm import object_session
    session = object_session(row)
    head = session.get(SettingsRow, f"kb_head:{row.id}") if session is not None else None
    digest = head.data["sha256"] if head else row.source_hashes.get("kb")
    return Dataset(
        dataset_id=row.id,
        name=row.name,
        mode=row.mode,
        parent_id=row.parent_id,
        source_hashes=row.source_hashes,
        row_counts=row.row_counts,
        version=row.version,
        created_at=row.created_at,
        kb_version=f"kb-{digest[:16]}" if digest else None,
    )


def records(session, dataset_id, kind):
    dataset(session, dataset_id)
    return list(
        session.scalars(
            select(RecordRow)
            .where(RecordRow.dataset_id == dataset_id, RecordRow.kind == kind)
            .order_by(RecordRow.source_row)
        )
    )


def safe_name(name):
    normalized = name.replace("\\", "/")
    p = PurePosixPath(normalized)
    if p.is_absolute() or ".." in p.parts or ":" in normalized or "\x00" in normalized:
        raise AppError(422, "UNSAFE_ARCHIVE_PATH", "Небезопасное имя файла в архиве.")
    return p.name


def runtime_file_allowed(name):
    filename = safe_name(name)
    return (
        filename.lower().endswith((".csv", ".json"))
        and not re.search(r"(?:^|_)KEY(?:[_.]|$)", filename, re.I)
        and filename.casefold() != "solution_example.csv"
    )


def unpack(files):
    output, warnings, total = [], [], 0
    for name, content in files:
        safe_name(name)
        total += len(content)
        if total > LIMIT:
            raise AppError(413, "IMPORT_TOO_LARGE", "Размер импорта превышает 50 МиБ.")
        if name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    members = archive.infolist()
                    if len(members) > 1000 or sum(m.file_size for m in members) > LIMIT:
                        raise AppError(413, "ARCHIVE_TOO_LARGE", "Архив превышает лимиты распаковки.")
                    for member in members:
                        safe_name(member.filename)
                        if member.is_dir():
                            continue
                        if member.flag_bits & 1 or (member.external_attr >> 16) & 0o170000 == 0o120000:
                            raise AppError(422, "UNSAFE_ARCHIVE", "Шифрованные файлы и ссылки запрещены.")
                        if not runtime_file_allowed(member.filename):
                            output.append((member.filename, b""))  # Inspect metadata, never evaluation body.
                            continue
                        output.append((member.filename, archive.read(member)))
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
                raise AppError(422, "INVALID_ZIP", "Архив поврежден или не поддерживается.") from None
        else:
            output.append((name, content))
    if sum(len(c) for _, c in output) > LIMIT:
        raise AppError(413, "IMPORT_TOO_LARGE", "Размер распакованных файлов превышает 50 МиБ.")
    accepted = []
    for name, content in output:
        filename = safe_name(name)
        if (
            re.search(r"(?:^|_)KEY(?:[_.]|$)", filename, re.I)
            or filename.lower().endswith(".py")
            or filename.casefold() == "solution_example.csv"
        ):
            warnings.append(f"{filename}: evaluation/служебный файл исключен из runtime")
        elif filename.lower().endswith((".csv", ".json")):
            accepted.append((filename, content))
        else:
            warnings.append(f"{filename}: не является входным CSV/KB")
    return accepted, warnings


def inspect_files(files, *, supply_reference=True, require_complete=True):
    files, warnings = unpack(files)
    parsed, errors, originals = {}, [], {}

    def error(name, row, field, raw, reason):
        errors.append(
            {"file": name, "row": str(row), "field": field, "raw": str(raw)[:1000], "reason": reason}
        )

    for filename, content in files:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            error(filename, 0, "encoding", "", "Требуется UTF-8")
            continue
        if content.startswith(b"\xef\xbb\xbf"):
            warnings.append(f"{filename}: BOM распознан, исходные байты сохранены")
        if filename.casefold().endswith(".json"):
            try:
                value = json.loads(
                    text, parse_float=str, parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
                )
                if (
                    not isinstance(value, dict)
                    or not isinstance(value.get("товары"), list)
                    or not value.get("правила")
                ):
                    raise ValueError()
                product_ids = [p.get("id") for p in value["товары"] if isinstance(p, dict)]
                if (
                    len(product_ids) != len(value["товары"])
                    or not all(product_ids)
                    or len(set(product_ids)) != len(product_ids)
                ):
                    raise ValueError()
                for product in value["товары"]:
                    if not all(
                        isinstance(product.get(k), str) and product[k].strip()
                        for k in ("id", "название", "вид")
                    ):
                        raise ValueError()
                    for field, price in product.items():
                        if (
                            field.startswith("цена")
                            and price is not None
                            and (isinstance(price, bool) or not re.fullmatch(r"\d+(?:\.\d+)?", str(price)))
                        ):
                            raise ValueError()
                if not isinstance(value["правила"], list) or any(
                    not isinstance(r, dict) or not r.get("id") or not isinstance(r.get("правило"), str)
                    for r in value["правила"]
                ):
                    raise ValueError()
                kind, rows = "kb", [{"public_id": "kb", "source_row": 1, "data": value}]
            except (ValueError, RecursionError):
                error(filename, 0, "json", "", "Ожидается KB: товары[] с уникальными id и правила")
                continue
        else:
            try:
                reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
                header = reader.fieldnames or []
                kinds = [k for k, schema in SCHEMAS.items() if set(header) - {LABEL} == set(schema)]
                if len(header) != len(set(header)) or not kinds:
                    error(filename, 1, "header", header, "Неизвестные, отсутствующие или повторные заголовки")
                    continue
                kind, rows = kinds[0], []
                if LABEL in header and kind != "applications":
                    error(filename, 1, "header", header, "Метка допустима только в applications")
                    continue
                seen = set()
                id_field = "part_id" if kind == "orders" else SCHEMAS[kind][0]
                for number, raw in enumerate(reader, 2):
                    if number > ROW_LIMIT + 1:
                        error(filename, number, "rows", "", "Превышен лимит 100000 строк")
                        break
                    if None in raw or any(v is None for v in raw.values()):
                        error(filename, number, "row", "", "Число значений не совпадает с заголовком")
                        continue
                    row = dict(raw)
                    for field, value in raw.items():
                        if len(value) > 16000:
                            error(filename, number, field, value, "Поле превышает 16000 символов")
                            continue
                        if not value.strip():
                            if kind == "applications" and field in OPTIONAL:
                                row[field] = None
                                continue
                            error(filename, number, field, value, "Обязательное значение отсутствует")
                            continue
                        if value != value.strip():
                            error(
                                filename,
                                number,
                                field,
                                value,
                                "Лишние пробелы; исходник не исправляется автоматически",
                            )
                        if field in FLAGS and value not in {"0", "1"}:
                            error(filename, number, field, value, "Допустимы 0/1")
                        if field in INTEGERS:
                            if (
                                len(value) > 10
                                or not re.fullmatch(r"\d+", value)
                                or (field in POSITIVE and int(value) <= 0)
                            ):
                                error(
                                    filename,
                                    number,
                                    field,
                                    value,
                                    "Требуется целое допустимое неотрицательное значение",
                                )
                            elif int(value) > 2_147_483_647:
                                error(
                                    filename, number, field, value, "Значение превышает допустимый диапазон"
                                )
                        if field in MONEY:
                            try:
                                if (
                                    not re.fullmatch(r"\d+(?:\.\d+)?", value)
                                    or not Decimal(value).is_finite()
                                ):
                                    raise InvalidOperation()
                            except InvalidOperation:
                                error(
                                    filename,
                                    number,
                                    field,
                                    value,
                                    "Требуется неотрицательное десятичное число",
                                )
                    if all(
                        len(raw.get(f, "")) <= 10 and re.fullmatch(r"\d+", raw.get(f, ""))
                        for f in ("длина_мм", "ширина_мм")
                    ):
                        if int(raw["длина_мм"]) < int(raw["ширина_мм"]):
                            error(
                                filename,
                                number,
                                "длина_мм",
                                raw["длина_мм"],
                                "Длина меньше ширины; исправьте явно",
                            )
                    public_id = raw[id_field]
                    if public_id in seen:
                        error(filename, number, id_field, public_id, "Повтор идентификатора")
                    if len(public_id) > 128:
                        error(filename, number, id_field, public_id, "ID длиннее 128 символов")
                    seen.add(public_id)
                    if kind == "applications" and raw["manager"] not in {"M1", "M2", "M3", "M4", "M5"}:
                        warnings.append(
                            f"{filename}:{number}: неизвестный менеджер; отдельная группа unknown"
                        )
                    rows.append({"public_id": public_id, "source_row": number, "data": row})
            except csv.Error:
                error(filename, 0, "csv", "", "Поврежденное CSV-экранирование")
                continue
        if kind in parsed:
            error(filename, 0, "kind", kind, "Несколько файлов одного типа")
        else:
            parsed[kind], originals[kind] = rows, (filename, content)
    if supply_reference:
        # Five-file closed import pins precisely the organizer reference sources.
        from glassflow.core.resources import resource_root

        reference = resource_root() / "inputs" / "PACK_for_teams"
        reference_files = []
        for kind, rel in {
            "materials": "1_ostatki/materials.csv",
            "kb": "2_assistant_crm/ksm_knowledge_base.json",
        }.items():
            if kind not in parsed and reference.joinpath(rel).is_file():
                reference_files.append((Path(rel).name, reference.joinpath(rel).read_bytes()))
                warnings.append(f"{kind}: добавлен неизмененный исходный справочник организаторов")
        if reference_files:
            extra, extra_originals, extra_errors, extra_warnings = inspect_files(
                reference_files, supply_reference=False, require_complete=False
            )
            parsed.update(extra)
            originals.update(extra_originals)
            errors.extend(extra_errors)
            warnings.extend(extra_warnings)
    for missing in {
        "materials",
        "stock",
        "orders",
        "questions",
        "dialogs",
        "applications",
        "kb",
    } - parsed.keys():
        if require_complete:
            error("", 0, "kind", missing, "Отсутствует обязательный тип входа")
    material_ids = {r["public_id"] for r in parsed.get("materials", [])}
    for kind in ("stock", "orders"):
        for row in parsed.get(kind, []):
            if row["data"]["material_id"] not in material_ids:
                error(
                    originals[kind][0],
                    row["source_row"],
                    "material_id",
                    row["data"]["material_id"],
                    "Неизвестный материал в этом наборе",
                )
    return parsed, originals, errors, warnings


def preview(session, files):
    parsed, originals, errors, warnings = inspect_files(files)
    report = {"row_counts": {k: len(v) for k, v in parsed.items()}, "errors": errors, "warnings": warnings}
    if "orders" in parsed:
        report["row_counts"]["distinct_orders"] = len({r["data"]["order_id"] for r in parsed["orders"]})
    staging = StagingRow(
        id=uid(),
        files=[
            {"kind": k, "name": n, "bytes": base64.b64encode(c).decode("ascii")}
            for k, (n, c) in originals.items()
        ],
        report=report,
    )
    session.add(staging)
    return {"import_id": staging.id, **report}


def commit(session, import_id, request, services, correlation):
    staging = session.get(StagingRow, import_id)
    if not staging:
        raise AppError(404, "IMPORT_NOT_FOUND", "Предпросмотр не найден.")
    if staging.report["errors"]:
        raise AppError(
            422, "IMPORT_INVALID", "Исправьте все ошибки импорта.", fields=staging.report["errors"]
        )
    files = [(f["name"], base64.b64decode(f["bytes"])) for f in staging.files]
    parsed, originals, errors, _ = inspect_files(files, supply_reference=False)
    if errors:
        raise AppError(422, "IMPORT_INVALID", "Повторная проверка не пройдена.", fields=errors)
    hashes = {kind: hashlib.sha256(c).hexdigest() for kind, (_, c) in originals.items()}
    fingerprint = canonical_hash(hashes)
    previous = session.scalar(
        select(DatasetRow).where(DatasetRow.fingerprint == fingerprint, DatasetRow.mode == request.mode)
    )
    if previous and not request.explicit_copy:
        return dataset_dto(previous).model_dump()
    result = DatasetRow(
        id=uid(),
        name=request.name,
        mode=request.mode,
        parent_id=previous.id if previous else None,
        fingerprint=fingerprint,
        source_hashes=hashes,
        row_counts=staging.report["row_counts"],
    )
    session.add(result)
    session.flush()
    for kind, rows in parsed.items():
        filename, content = originals[kind]
        session.add(
            SourceRow(
                dataset_id=result.id,
                kind=kind,
                filename=filename,
                content=content,
                sha256=hashes[kind],
                row_count=len(rows),
            )
        )
        for row in rows:
            session.add(RecordRow(dataset_id=result.id, kind=kind, **row))
    session.flush()
    for hook in services.import_hooks:
        hook(session, result.id, parsed)
    audit(session, result.id, "import.commit", result.id, correlation)
    session.flush()
    return dataset_dto(result).model_dump()


def working_copy(session, source_id, name, services, correlation, mode="workspace"):
    source = dataset(session, source_id)
    copy = DatasetRow(
        id=uid(),
        name=name,
        mode=mode,
        parent_id=source.id,
        fingerprint=source.fingerprint,
        source_hashes=dict(source.source_hashes),
        row_counts=dict(source.row_counts),
    )
    session.add(copy)
    session.flush()
    for row in session.scalars(
        select(SourceRow)
        .where(SourceRow.dataset_id == source_id)
        .order_by(SourceRow.imported_at, SourceRow.id)
    ):
        session.add(
            SourceRow(
                dataset_id=copy.id,
                kind=row.kind,
                filename=row.filename,
                sha256=row.sha256,
                content=row.content,
                row_count=row.row_count,
                imported_at=row.imported_at,
            )
        )
    grouped = {}
    for row in session.scalars(select(RecordRow).where(RecordRow.dataset_id == source_id)):
        data = {"public_id": row.public_id, "source_row": row.source_row, "data": row.data}
        session.add(RecordRow(dataset_id=copy.id, kind=row.kind, **data))
        grouped.setdefault(row.kind, []).append(data)
    session.flush()
    kb_pointer = session.get(SettingsRow, f"kb_head:{source_id}")
    if kb_pointer:
        session.add(
            SettingsRow(id=f"kb_head:{copy.id}", version=kb_pointer.version, data=dict(kb_pointer.data))
        )
    for hook in services.import_hooks:
        hook(session, copy.id, grouped)
    audit(session, copy.id, "dataset.working_copy", copy.id, correlation)
    session.flush()
    return dataset_dto(copy).model_dump()
