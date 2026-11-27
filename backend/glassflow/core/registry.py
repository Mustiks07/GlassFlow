"""Explicit composition seams. Missing dependencies fail closed; no fixture fallback."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from glassflow.core.errors import AppError
from glassflow.ports import OrderSourcePort, SalesSourcePort


class SubjectResolver(Protocol):
    def check(
        self,
        session,
        dataset_id: str,
        subject_type: str,
        subject_ref: str,
        expected_version: int | None,
        *,
        compatibility_ref: str | None = None,
        compatibility_version: int | None = None,
    ) -> dict: ...


@dataclass
class Services:
    # Called inside the import transaction, may flush, must not commit or call network.
    import_hooks: list = field(default_factory=list)
    subjects: SubjectResolver | None = None
    sales_source: SalesSourcePort | None = None
    order_source: OrderSourcePort | None = None
    # job kind -> importable handler callable(snapshot, context), no user-supplied paths.
    job_handlers: dict = field(default_factory=dict)
    ai_check: Any = None
    readiness: dict = field(default_factory=dict)
    result_hooks: dict = field(default_factory=dict)

    def check_subject(
        self,
        session,
        dataset_id,
        subject_type,
        subject_ref,
        version,
        compatibility_ref=None,
        compatibility_version=None,
    ):
        if subject_type == "interest":
            if not subject_ref or not subject_ref.strip():
                raise AppError(422, "SUBJECT_REQUIRED", "Укажите товарную группу.")
            return {"valid": True, "version": None}
        if self.subjects is None:
            raise AppError(503, "SUBJECT_SERVICE_UNAVAILABLE", "Проверка предмета пока не подключена.")
        if not subject_ref:
            raise AppError(422, "SUBJECT_REQUIRED", "Укажите ссылку на предмет задачи.")
        if subject_type == "specific_remnant":
            if compatibility_ref is None or compatibility_version is None:
                raise AppError(
                    422,
                    "COMPATIBILITY_REQUIRED",
                    "Нужен явный расчет/деталь и версия для проверки совместимости куска.",
                )
            result = self.subjects.check(
                session,
                dataset_id,
                subject_type,
                subject_ref,
                version,
                compatibility_ref=compatibility_ref,
                compatibility_version=compatibility_version,
            )
            if "compatibility_version" not in result or "compatibility_valid" not in result:
                raise AppError(
                    503, "COMPATIBILITY_NOT_CHECKED", "Источник не подтвердил совместимость и ее версию."
                )
            return {
                **result,
                "valid": result["valid"]
                and result["compatibility_valid"]
                and result["compatibility_version"] == compatibility_version,
            }
        return self.subjects.check(session, dataset_id, subject_type, subject_ref, version)
