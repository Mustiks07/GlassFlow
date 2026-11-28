"""Database-backed C3 IntelligenceSources protocol: original bytes and versioned workspace KB."""

import hashlib
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import or_, select, text

from glassflow.core.errors import AppError
from glassflow.core.models import SettingsRow, SourceRow
from glassflow.modules.platform.imports import dataset


@dataclass(frozen=True)
class SourceDocument:
    dataset_id: str
    kind: str
    name: str
    content: bytes
    origin: str

    @property
    def sha256(self):
        return hashlib.sha256(self.content).hexdigest()


class PlatformIntelligenceSources:
    def __init__(self, factory, bound_session=None):
        self.factory = factory
        self.bound_session = bound_session

    @contextmanager
    def reading(self):
        if self.bound_session is not None:
            yield self.bound_session
        else:
            with self.factory() as session:
                session.execute(text("BEGIN"))
                yield session

    def kb_history(self, dataset_id):
        with self.reading() as session:
            return self._history(session, dataset_id)

    def _history(self, session, dataset_id):
        dataset(session, dataset_id)
        rows = session.scalars(
            select(SourceRow)
            .where(
                SourceRow.dataset_id == dataset_id,
                or_(SourceRow.kind == "kb", SourceRow.kind.like("kb_revision:%")),
            )
            .order_by(SourceRow.imported_at, SourceRow.id)
        ).all()
        return [
            SourceDocument(
                dataset_id,
                "kb",
                r.filename,
                r.content,
                "platform_snapshot" if r.kind == "kb" else "workspace_kb_revision",
            )
            for r in rows
        ]

    def knowledge_base(self, dataset_id, version=None):
        with self.reading() as session:
            history = self._history(session, dataset_id)
            if not history:
                raise AppError(404, "KB_NOT_FOUND", "База знаний не найдена в этом наборе.")
            head = session.get(SettingsRow, f"kb_head:{dataset_id}")
            digest = head.data["sha256"] if head else history[0].sha256
            if version is None:
                return next(d for d in history if d.sha256 == digest)
        for document in history:
            if version in {document.sha256, f"sha256:{document.sha256}", f"kb-{document.sha256[:16]}"}:
                return document
        raise AppError(
            409, "STALE_KB_VERSION", "Версия KB отсутствует в этом наборе.", conflicts=[f"kb-{digest[:16]}"]
        )

    def materials(self, dataset_id):
        with self.reading() as session:
            dataset(session, dataset_id)
            row = session.scalar(
                select(SourceRow).where(SourceRow.dataset_id == dataset_id, SourceRow.kind == "materials")
            )
            return (
                SourceDocument(dataset_id, "materials", row.filename, row.content, "platform_snapshot")
                if row
                else None
            )
