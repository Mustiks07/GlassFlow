import hashlib
import json
from contextlib import contextmanager

from sqlalchemy import text

from glassflow.core.errors import AppError
from glassflow.core.models import AuditRow, IdempotencyRow, ObjectRow


def canonical_hash(body) -> str:
    return hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@contextmanager
def write_transaction(factory):
    """Reserve SQLite writer before reading versions. No CPU/network work inside."""
    with factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise


def idempotent(session, dataset_id, operation, key, body, action):
    if not key or len(key) > 128:
        raise AppError(422, "IDEMPOTENCY_KEY_REQUIRED", "Нужен Idempotency-Key длиной до 128 символов.")
    digest = canonical_hash(body)
    previous = session.get(IdempotencyRow, (dataset_id, operation, key))
    if previous:
        if previous.request_hash != digest:
            raise AppError(409, "IDEMPOTENCY_CONFLICT", "Ключ уже использован с другим запросом.")
        return previous.result
    result = action()
    session.add(
        IdempotencyRow(
            dataset_id=dataset_id, operation=operation, key=key, request_hash=digest, result=result
        )
    )
    return result


def audit(session, dataset_id, action, object_id, correlation_id, **versions):
    session.add(
        AuditRow(
            dataset_id=dataset_id,
            action=action,
            object_id=object_id,
            correlation_id=correlation_id,
            versions=versions,
        )
    )


def get_object(session, dataset_id, kind, object_id, expected_version=None):
    row = session.get(ObjectRow, (dataset_id, kind, object_id))
    if row is None:
        raise AppError(404, "NOT_FOUND", "Объект не найден в этом наборе.")
    if expected_version is not None and row.version != expected_version:
        raise AppError(
            409,
            "VERSION_CONFLICT",
            "Объект изменен; перечитайте текущую версию.",
            conflicts=[f"{kind}:{object_id}:{row.version}"],
        )
    return row
