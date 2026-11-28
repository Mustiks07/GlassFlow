"""Local owner operations; secrets stay only in session memory."""

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from glassflow.contracts.platform import AISettings
from glassflow.core.db import SCHEMA_HEAD, backup_database
from glassflow.core.errors import AppError
from glassflow.core.models import SettingsRow, now, uid


def get_settings(session, secrets):
    row = session.get(SettingsRow, "ai")
    data = dict(row.data) if row else AISettings().model_dump()
    data["version"] = row.version if row else 0
    data["secret_present"] = bool(secrets.get(f"{data['profile']}:{data['provider']}"))
    return AISettings.model_validate(data)


def save_settings(session, body, secrets):
    previous = get_settings(session, secrets)
    if previous.version != body.version:
        raise AppError(409, "VERSION_CONFLICT", "Настройки изменились; перечитайте их.")
    if body.mode == "free_only" and (body.paid_enabled or Decimal(body.monthly_budget_tg) != 0):
        raise AppError(422, "FREE_ONLY_BUDGET", "В бесплатном режиме paid_enabled=false и бюджет=0.")
    if body.mode == "paid_enabled" and (not body.paid_enabled or Decimal(body.monthly_budget_tg) <= 0):
        raise AppError(
            422, "PAID_OPT_IN_REQUIRED", "Для платного режима явно включите оплату и положительный бюджет."
        )
    if body.profile == "judge_gateway":
        from urllib.parse import urlsplit

        parsed = urlsplit(body.gateway_url or "")
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
        ):
            raise AppError(422, "HTTPS_GATEWAY_REQUIRED", "Нужен HTTPS-адрес шлюза без токена в URL.")
    data = body.model_dump(exclude={"api_key", "secret_present"})
    data["version"] = previous.version + 1
    row = session.get(SettingsRow, "ai")
    if row is None:
        row = SettingsRow(id="ai", version=data["version"], data=data)
        session.add(row)
    else:
        row.version, row.data = data["version"], data
    # Caller installs the secret after the DB transaction succeeds.
    return {
        **data,
        "secret_present": bool(body.api_key) if body.api_key is not None else previous.secret_present,
    }


def backup_path(data_dir, backup_id):
    try:
        if str(UUID(backup_id)) != backup_id:
            raise ValueError()
    except ValueError:
        raise AppError(404, "BACKUP_NOT_FOUND", "Копия не найдена.") from None
    path = data_dir / "backups" / f"{backup_id}.db"
    if not path.is_file():
        raise AppError(404, "BACKUP_NOT_FOUND", "Копия не найдена.")
    return path


def create_backup(data_dir):
    backup_id = uid()
    directory = data_dir / "backups"
    directory.mkdir(exist_ok=True)
    temporary = directory / f".{backup_id}.tmp"
    backup_database(data_dir / "glassflow.db", temporary)
    final = directory / f"{backup_id}.db"
    os.replace(temporary, final)
    return {
        "backup_id": backup_id,
        "sha256": hashlib.sha256(final.read_bytes()).hexdigest(),
        "created_at": now(),
        "integrity": "ok",
    }


def validate_backup(path):
    try:
        # mode=ro prevents accidentally creating an empty database on a bad reference.
        with closing(sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError()
            backup_version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            if backup_version not in {
                ("0001_platform",),
                ("0002_immutable_history",),
                (SCHEMA_HEAD,),
            }:
                raise ValueError()
            tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if (backup_version not in {("0001_platform",), ("0002_immutable_history",)}
                    and "material_usage" not in tables):
                raise ValueError()
            if (
                not {"datasets", "source_files", "source_records", "platform_objects", "jobs", "settings"}
                <= tables
            ):
                raise ValueError()
            if list(connection.execute("PRAGMA foreign_key_check")):
                raise ValueError()
    except (sqlite3.Error, ValueError, TypeError):
        raise AppError(422, "BACKUP_INVALID", "Копия повреждена или версия схемы несовместима.") from None


def request_restore(data_dir, body):
    if not body.confirm_replace:
        raise AppError(422, "EXPLICIT_RESTORE_REQUIRED", "Подтвердите замену базы при следующем запуске.")
    path = backup_path(data_dir, body.backup_id)
    validate_backup(path)
    protected = create_backup(data_dir)
    manifest = {
        "backup_id": body.backup_id,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "protected_backup_id": protected["backup_id"],
    }
    temporary = data_dir / ".pending-restore.tmp"
    temporary.write_text(json.dumps(manifest), encoding="utf8")
    os.replace(temporary, data_dir / "pending-restore.json")
    return {"status": "pending_restart", **manifest}


def apply_pending_restore(data_dir):
    """Run only before opening engine and while the launcher owns the instance lock."""
    marker = data_dir / "pending-restore.json"
    if not marker.is_file():
        return
    manifest = json.loads(marker.read_text(encoding="utf8"))
    path = backup_path(data_dir, manifest["backup_id"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["sha256"]:
        raise AppError(422, "BACKUP_CHANGED", "Копия изменилась после выбора.")
    validate_backup(path)
    staged = data_dir / ".restored-database.tmp"
    backup_database(path, staged)
    validate_backup(staged)
    # No running connections here. Back up the very last state as well as the API-time backup.
    if (data_dir / "glassflow.db").exists():
        create_backup(data_dir)
    for suffix in ("-wal", "-shm"):
        (data_dir / f"glassflow.db{suffix}").unlink(missing_ok=True)
    os.replace(staged, data_dir / "glassflow.db")
    marker.unlink()
