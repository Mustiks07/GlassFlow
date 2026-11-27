"""One-run strict CSV exporter. Pricing/answers/geometry come from their owning services."""

import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from sqlalchemy import select

from glassflow.core.errors import AppError
from glassflow.core.models import SourceRow, uid
from glassflow.core.uow import get_object, write_transaction
from glassflow.modules.platform.imports import records
from glassflow.modules.platform.runs import MODULE_FILES, find_run, latest_jobs
from glassflow.modules.sales.service import BUYER_FIELDS, recheck_card, registry

SCHEMAS = {
    "solution.csv": ["part_id", "remnant_id", "x_mm", "y_mm", "rot"],
    "sale_cards.csv": ["remnant_id", "title", "price_tg", "description", "target_buyer", "top3_buyers"],
    "answers.csv": ["id", "answer"],
    "picks.csv": ["app_id"],
    "verdicts.csv": ["id", "verdict", "correct"],
    "buyers_top50.csv": BUYER_FIELDS,
}


def csv_bytes(name, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=SCHEMAS[name], extrasaction="raise", lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    data = stream.getvalue().encode("utf-8")
    reread = list(csv.DictReader(io.StringIO(data.decode("utf8"), newline=""), strict=True))
    if len(reread) != len(rows) or data.startswith(b"\xef\xbb\xbf"):
        raise AppError(409, "CSV_ROUNDTRIP_FAILED", "Не пройдена повторная проверка CSV.")
    return data


def ids_equal(rows, field, expected):
    ids = [r.get(field) for r in rows]
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        raise AppError(409, "EXPORT_ID_MISMATCH", "Пропущенные, повторные или чужие ID в результате.")


def exact_rows(name, rows):
    if not isinstance(rows, list) or any(
        not isinstance(r, dict) or set(r) != set(SCHEMAS[name]) for r in rows
    ):
        raise AppError(409, "EXPORT_SCHEMA_MISMATCH", "Результат не соответствует точным колонкам CSV.")
    return [{k: "" if v is None else str(v) for k, v in r.items()} for r in rows]


def validate_rows(session, dataset_id, name, rows, plan_used=None):
    rows = exact_rows(name, rows)
    if name == "solution.csv":
        ids_equal(rows, "part_id", [r.public_id for r in records(session, dataset_id, "orders")])
        originals = {r.public_id for r in records(session, dataset_id, "stock")}
        for row in rows:
            if row["remnant_id"] == "NEW":
                if any(row[f] for f in ("x_mm", "y_mm", "rot")):
                    raise AppError(
                        409, "NEW_FIELDS_NOT_EMPTY", "Для NEW координаты и поворот должны быть пустыми."
                    )
            elif (
                row["remnant_id"] not in originals
                or row["rot"] not in {"0", "1"}
                or any(not re.fullmatch(r"\d+", row[f]) for f in ("x_mm", "y_mm"))
            ):
                raise AppError(409, "INVALID_PLACEMENT_FORMAT", "Неверные ID, целые координаты или поворот.")
    elif name == "picks.csv":
        allowed = {r.public_id for r in records(session, dataset_id, "applications")}
        chosen = [r["app_id"] for r in rows]
        if len(chosen) != 25 or len(set(chosen)) != 25 or not set(chosen) <= allowed:
            raise AppError(409, "INVALID_PICKS", "Нужно 25 разных app_id текущего снимка.")
    elif name in {"answers.csv", "verdicts.csv"}:
        kind = "questions" if name == "answers.csv" else "dialogs"
        ids_equal(rows, "id", [r.public_id for r in records(session, dataset_id, kind)])
        for row in rows:
            if name == "answers.csv" and not row["answer"].strip():
                raise AppError(409, "EMPTY_ANSWER", "Обязательный ответ отсутствует.")
            if name == "verdicts.csv" and (
                row["verdict"] not in {"OK", "ERROR"}
                or (row["verdict"] == "ERROR" and not re.fullmatch(r"\d+(?:\.\d+)?", row["correct"]))
                or (row["verdict"] == "OK" and row["correct"] != "")
            ):
                raise AppError(409, "UNRESOLVED_VERDICT", "Нужен OK с пустым correct или ERROR с числом.")
    elif name == "sale_cards.csv":
        original = {r.public_id for r in records(session, dataset_id, "stock")}
        chosen = [r["remnant_id"] for r in rows]
        if (
            len(rows) != 5
            or len(set(chosen)) != 5
            or not set(chosen) <= original
            or set(chosen) & set(plan_used or [])
        ):
            raise AppError(
                409, "INVALID_CARDS", "Нужны пять разных целых свободных исходных кусков выбранного плана."
            )
        for row in rows:
            names = row["top3_buyers"].split(";")
            if len(names) != 3 or len(set(names)) != 3 or not re.fullmatch(r"\d+(?:\.\d+)?", row["price_tg"]):
                raise AppError(409, "INVALID_CARD_VALUES", "Неверная цена или top3.")
    return rows


def official_cutting(staging, source_files, solution):
    from glassflow.core.resources import resource_root

    organizer = resource_root() / "inputs" / "PACK_for_teams" / "1_ostatki" / "validate.py"
    if not organizer.is_file():
        raise AppError(503, "OFFICIAL_VALIDATOR_MISSING", "Не найден неизмененный validate.py.")
    for kind in ("stock", "orders", "materials"):
        (staging / f"input-{kind}.csv").write_bytes(source_files[kind])
    command = [
        sys.executable,
        "-X",
        "utf8",
        str(organizer),
        str(staging / "input-stock.csv"),
        str(staging / "input-orders.csv"),
        str(solution),
        str(staging / "input-materials.csv"),
    ]
    if getattr(sys, "frozen", False):
        # Frozen exe is not a general Python interpreter; its protected CLI executes only this bundled script.
        diagnostics = Path(sys.executable).with_name("GlassFlowDiagnostics.exe")
        if not diagnostics.is_file():
            raise AppError(
                503, "DIAGNOSTICS_BINARY_MISSING", "Неполный комплект: нет GlassFlowDiagnostics.exe."
            )
        command = [str(diagnostics), "--official-validator", str(staging)]
    environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        command,
        capture_output=True,
        encoding="utf8",
        errors="replace",
        env=environment,
        timeout=60,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    output = result.stdout
    passed = result.returncode == 0 and bool(re.search(r"RESULT .*invalid=0\b", output))
    report = {
        "script": "validate.py",
        "script_sha256": hashlib.sha256(organizer.read_bytes()).hexdigest(),
        "exit_code": result.returncode,
        "stdout": output,
        "stderr": result.stderr,
        "passed": passed,
    }
    for path in staging.glob("input-*.csv"):
        path.unlink()
    return report


def prepare_export(session, run_id, services, correlation):
    run = find_run(session, run_id)
    jobs = latest_jobs(session, run_id)
    sources = {
        r.kind: r.content
        for r in session.scalars(select(SourceRow).where(SourceRow.dataset_id == run.dataset_id))
    }
    prepared, errors, validators = {}, [], {}
    cutting_rows, plan_ref = None, None
    cut = jobs.get("cutting")
    if cut and cut.state == "completed" and cut.result:
        plan_ref = (cut.result.get("plan_id"), cut.result.get("plan_revision"))
    for module, name in MODULE_FILES.items():
        job = jobs.get(module)
        if not job or job.state != "completed" or job.result is None:
            errors.append(f"{module}: результат не завершен")
            continue
        try:
            rows = job.result.get("rows")
            if module == "cards":
                if not plan_ref or (job.result.get("plan_id"), job.result.get("plan_revision")) != plan_ref:
                    raise AppError(409, "CARD_PLAN_MISMATCH", "Карточки относятся к другой ревизии плана.")
                rows = []
                for card_id in job.result.get("card_ids", []):
                    stored = get_object(session, run.dataset_id, "sale_card", card_id)
                    card = recheck_card(session, stored, services, correlation)
                    if card.status != "ready" or (card.plan_id, card.plan_revision) != plan_ref:
                        raise AppError(409, "STALE_CARD", "Карточка устарела.")
                    rows.append(
                        {
                            k: ";".join(card.top3_buyers) if k == "top3_buyers" else getattr(card, k)
                            for k in SCHEMAS[name]
                        }
                    )
            if module == "cutting" and (
                not all(v is not None for v in plan_ref) or not job.result.get("validated")
            ):
                raise AppError(409, "UNVERIFIED_PLAN", "Нет ссылки на проверенную ревизию плана.")
            if module == "assistant" and job.result.get("needs_review"):
                raise AppError(409, "UNVERIFIED_ANSWERS", "Ответы требуют проверки.")
            used = [r["remnant_id"] for r in cutting_rows] if cutting_rows else []
            checked = validate_rows(session, run.dataset_id, name, rows, used)
            prepared[name] = csv_bytes(name, checked)
            if module == "cutting":
                cutting_rows = checked
        except (AppError, TypeError, KeyError) as exc:
            errors.append(f"{module}: {exc.code if isinstance(exc, AppError) else 'INVALID_RESULT'}")
    buyer_version = run.data.get("buyer_registry_version")
    if buyer_version:
        try:
            buyers = registry(session, run.dataset_id, buyer_version).data["buyers"]
            prepared["buyers_top50.csv"] = csv_bytes(
                "buyers_top50.csv", [{k: b[k] for k in BUYER_FIELDS} for b in buyers]
            )
        except AppError as exc:
            errors.append(f"buyers: {exc.code}")
    else:
        errors.append("buyers: реестр не закреплен")
    return (
        run.dataset_id,
        deepcopy(run.data),
        sources,
        prepared,
        errors,
        validators,
        {k: {"job_id": v.id, "state": v.state} for k, v in jobs.items()},
        {k: deepcopy((v.result or {}).get("provenance", {"status": "not_recorded"}))
         for k, v in jobs.items()},
    )


def export_run(factory, run_id, data_dir, services, correlation):
    # Recheck + capture in a short writer transaction; external validator holds no DB lock.
    with write_transaction(factory) as session:
        dataset_id, run_data, sources, prepared, errors, validators, result_refs, provenance = prepare_export(
            session, run_id, services, correlation
        )
    export_id = uid()
    root = data_dir / "exports" / run_id
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".staging-{export_id}"
    final = root / export_id
    if staging.resolve().parent != root.resolve() or final.resolve().parent != root.resolve():
        raise AppError(422, "UNSAFE_EXPORT_PATH", "Путь экспорта выходит за выделенный каталог.")
    staging.mkdir()
    try:
        for name, content in prepared.items():
            path = staging / name
            with path.open("wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if path.read_bytes() != content:
                raise AppError(409, "EXPORT_WRITE_FAILED", "Повторное чтение файла не совпало.")
        if "solution.csv" in prepared:
            try:
                validators["cutting_official"] = official_cutting(staging, sources, staging / "solution.csv")
                if not validators["cutting_official"]["passed"]:
                    raise AppError(409, "OFFICIAL_VALIDATION_FAILED", "Официальная проверка не пройдена.")
            except AppError as exc:
                errors.append(f"cutting: {exc.code}")
                prepared.pop("solution.csv")
                (staging / "solution.csv").unlink()
                if "sale_cards.csv" in prepared:
                    prepared.pop("sale_cards.csv")
                    (staging / "sale_cards.csv").unlink()
        status = (
            "ready" if set(prepared) == set(SCHEMAS) and not errors else "partial" if prepared else "blocked"
        )
        hashes = {name: hashlib.sha256(content).hexdigest() for name, content in prepared.items()}
        manifest = {
            **run_data,
            "export_id": export_id,
            "status": status,
            "errors": errors,
            "files": hashes,
            "validators": validators,
            "result_refs": result_refs,
            "module_provenance": provenance,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
        )
        os.replace(staging, final)
        with write_transaction(factory) as session:
            run = get_object(session, dataset_id, "run", run_id)
            run.data = {**run.data, "last_export_id": export_id, "files": hashes, "validators": validators}
        return {
            "run_id": run_id,
            "status": status,
            "files": {
                name: f"/api/v1/runs/{run_id}/files/{export_id}/{name}"
                for name in [*prepared, "manifest.json"]
            },
            "errors": errors,
        }
    except BaseException:
        if staging.resolve().parent == root.resolve() and staging.name.startswith(".staging-"):
            shutil.rmtree(staging, ignore_errors=True)
        raise
