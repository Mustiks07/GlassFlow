import hashlib

from sqlalchemy import select

from glassflow.core.errors import AppError
from glassflow.core.models import SettingsRow, SourceRow
from glassflow.core.uow import audit
from glassflow.modules.platform.imports import dataset, inspect_files


def kb_head(session, dataset_id):
    dataset(session, dataset_id)
    head = session.get(SettingsRow, f"kb_head:{dataset_id}")
    original = session.scalar(
        select(SourceRow).where(SourceRow.dataset_id == dataset_id, SourceRow.kind == "kb")
    )
    if original is None:
        raise AppError(404, "KB_NOT_FOUND", "База знаний не найдена.")
    digest = head.data["sha256"] if head else original.sha256
    return {
        "dataset_id": dataset_id,
        "kb_version": f"kb-{digest[:16]}",
        "sha256": digest,
        "version": head.version if head else 0,
    }


def revise_kb(session, dataset_id, content, filename, expected_version, correlation):
    record = dataset(session, dataset_id)
    if record.mode != "workspace":
        raise AppError(409, "IMMUTABLE_DATASET", "Изменение KB разрешено только в рабочей копии.")
    current = kb_head(session, dataset_id)
    if current["version"] != expected_version:
        raise AppError(409, "VERSION_CONFLICT", "База знаний изменилась; перечитайте актуальную версию.")
    parsed, _, errors, _ = inspect_files(
        [(filename, content)], supply_reference=False, require_complete=False
    )
    if errors or set(parsed) != {"kb"}:
        raise AppError(422, "KB_INVALID", "Файл KB не прошел проверку.", fields=errors)
    digest = hashlib.sha256(content).hexdigest()
    if digest == current["sha256"]:
        return current
    known = session.scalar(
        select(SourceRow).where(
            SourceRow.dataset_id == dataset_id,
            SourceRow.sha256 == digest,
            (SourceRow.kind == "kb") | SourceRow.kind.like("kb_revision:%"),
        )
    )
    if known is None:
        session.add(
            SourceRow(
                dataset_id=dataset_id,
                kind=f"kb_revision:{digest}",
                filename=filename,
                content=content,
                sha256=digest,
                row_count=1,
            )
        )
    head = session.get(SettingsRow, f"kb_head:{dataset_id}")
    if head is None:
        head = SettingsRow(id=f"kb_head:{dataset_id}", version=1, data={"sha256": digest})
        session.add(head)
    else:
        head.version += 1
        head.data = {"sha256": digest}
    audit(
        session, dataset_id, "kb.revise", digest, correlation, before=current["version"], after=head.version
    )
    session.flush()
    return kb_head(session, dataset_id)
