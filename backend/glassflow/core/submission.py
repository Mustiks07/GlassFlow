"""C2's requested platform submitter; no solver implementation or nested transaction."""

import os

from glassflow.core.errors import AppError
from glassflow.core.jobs import enqueue, job_dto
from glassflow.core.uow import write_transaction
from glassflow.modules.platform.imports import dataset


class DurableJobSubmitter:
    def __init__(self, factory, handlers):
        self.factory, self.handlers = factory, handlers

    def submit(self, kind: str, dataset_id: str, payload: dict):
        target = "cutting" if kind == "cutting.solve" else kind
        if target not in self.handlers:
            raise AppError(
                503, "JOB_HANDLER_UNAVAILABLE", "Вычислительный сервис пока не подключен.", retryable=True
            )
        if payload.get("dataset_id") != dataset_id:
            raise AppError(422, "SNAPSHOT_SCOPE_MISMATCH", "Снимок относится к другому набору.")
        if kind == "cutting.solve":
            config = payload.get("config", {})
            workers, budget = config.get("workers", 1), config.get("time_limit_seconds", 60)
            if type(workers) is not int or not 1 <= workers <= max(1, (os.cpu_count() or 1) - 1):
                raise AppError(422, "CPU_BUDGET_EXCEEDED", "Недопустимое число вычислительных потоков.")
            if type(budget) is not int or not 1 <= budget <= 3600:
                raise AppError(422, "TIME_BUDGET_EXCEEDED", "Бюджет задания должен быть от 1 до 3600 секунд.")
            snapshot = {
                "dataset_id": dataset_id,
                "cutting_snapshot": payload,
                "solver_config": config,
                "base_plan_id": payload.get("base_plan_id"),
                "requested_operation": kind,
            }
        else:
            snapshot = payload
        with write_transaction(self.factory) as session:
            dataset(session, dataset_id)
            job = enqueue(session, dataset_id, target, snapshot)
            session.flush()
            return job_dto(job)
