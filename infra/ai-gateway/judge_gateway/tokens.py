"""Revocable competition tokens: issue (plaintext shown once), verify, revoke."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import TokenRecord

PREFIX = "gfj_"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue(path: Path, *, label: str, days: int = 3, max_requests: int = 500) -> tuple[str, TokenRecord]:
    token = PREFIX + secrets.token_urlsafe(32)
    record = TokenRecord(
        token_id="jt-" + secrets.token_hex(4),
        sha256=hash_token(token),
        expires_at=datetime.now(UTC) + timedelta(days=days),
        label=label,
        max_requests=max_requests,
    )
    records = load(path)
    records.append(record)
    save(path, records)
    return token, record


def revoke(path: Path, token_id: str) -> bool:
    records = load(path)
    changed = False
    for record in records:
        if record.token_id == token_id and not record.revoked:
            record.revoked = True
            changed = True
    save(path, records)
    return changed


def load(path: Path) -> list[TokenRecord]:
    if not path.is_file():
        return []
    return [TokenRecord.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]


def save(path: Path, records: list[TokenRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps([r.model_dump(mode="json") for r in records], indent=2), encoding="utf-8")
    temporary.replace(path)


def verify(token: str, records: list[TokenRecord], now: datetime | None = None) -> tuple[TokenRecord | None, str]:
    now = now or datetime.now(UTC)
    digest = hash_token(token)
    for record in records:
        if hmac.compare_digest(record.sha256, digest):
            if record.revoked:
                return None, "token_revoked"
            expires = record.expires_at if record.expires_at.tzinfo else record.expires_at.replace(tzinfo=UTC)
            if expires <= now:
                return None, "token_expired"
            return record, "ok"
    return None, "token_unknown"
