"""Coordinator dependency fault regression; real changed-input TCP evidence is separate."""
import time

from sqlalchemy import func, select

from glassflow.core.jobs import Coordinator, enqueue
from glassflow.core.models import JobRow, ObjectRow, uid
from glassflow.core.uow import write_transaction
from glassflow.modules.platform.budgets import create_budget
from glassflow.modules.platform.runs import schedule_cards


def test_failed_budget_cutting_schedules_one_dependency_result_per_attempt_across_restart(client, imported):
    client.app.state.coordinator.stop()
    factory = client.app.state.session_factory
    run_id = uid()
    with write_transaction(factory) as session:
        session.add(ObjectRow(dataset_id=imported["dataset_id"], kind="run", id=run_id, version=0,
            data={"modules": ["cutting", "cards"], "budget": create_budget(120, 30, {"profile": "quick"})}))
        failed = enqueue(session, imported["dataset_id"], "cutting", {}, run_id)
        failed.state, failed.stopped, failed.error_code = "failed", True, "RUN_WORK_BUDGET_EXCEEDED"
        first_cutting_id = failed.id

    def count_cards():
        with factory() as session:
            return session.scalar(select(func.count()).select_from(JobRow).where(JobRow.run_id == run_id,
                JobRow.kind == "cards"))

    for _ in range(8):
        schedule_cards(factory)
    assert count_cards() == 1
    with factory() as session:
        card = session.scalar(select(JobRow).where(JobRow.run_id == run_id, JobRow.kind == "cards"))
        assert card.input["cutting_job_id"] == first_cutting_id and card.error_code == "CUTTING_NOT_COMPLETED"
    for _ in range(2):
        coordinator = Coordinator(factory, {}, tick=lambda: schedule_cards(factory))
        coordinator.start()
        try:
            time.sleep(.35)
            assert coordinator.healthy and count_cards() == 1
        finally:
            coordinator.stop()
    # An explicit new cutting attempt has its own dependency outcome, exactly once.
    with write_transaction(factory) as session:
        next_cutting = enqueue(session, imported["dataset_id"], "cutting", {}, run_id)
        next_cutting.state, next_cutting.stopped = "failed", True
        next_cutting.error_code = "WORKER_FAILED"
    for _ in range(8):
        schedule_cards(factory)
    assert count_cards() == 2
