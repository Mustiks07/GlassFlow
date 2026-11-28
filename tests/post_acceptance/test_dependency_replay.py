"""Coordinator dependency fault regression; real changed-input TCP evidence is separate."""
import time
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from glassflow.core.jobs import Coordinator, enqueue
from glassflow.core.models import JobRow, ObjectRow, uid
from glassflow.core.uow import write_transaction
from glassflow.modules.platform.budgets import create_budget, utc_now
from glassflow.modules.platform.runs import run_view, schedule_cards


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


def completed_before_tick(factory, dataset_id, *, cards=False, budget=True):
    run_id = uid()
    data = {"modules": ["cutting", "assistant", "quality", "crm", "cards"], "buyer_registry_version": "test-registry"}
    if budget:
        data["budget"] = create_budget(120, 30, {"profile": "extended", "time_limit_seconds": 6})
    with write_transaction(factory) as session:
        session.add(ObjectRow(dataset_id=dataset_id, kind="run", id=run_id, version=0, data=data))
        refs = {}
        cutting_id = None
        for kind in ["cutting", "assistant", "quality", "crm"] + (["cards"] if cards else []):
            job = enqueue(session, dataset_id, kind,
                {"cutting_job_id": cutting_id} if kind == "cards" else {"cutting_snapshot": {}, "solver_config": {}}, run_id)
            job.state, job.stopped, job.result = "completed", True, {"metrics": {"covered_area_mm2": 10}}
            if kind == "cutting":
                cutting_id = job.id
            refs[kind] = {"job_id": job.id, "state": "completed"}
    return run_id, refs


@pytest.mark.parametrize("with_budget", [False, True])
def test_run_waits_for_cards_before_first_coordinator_tick(client, imported, with_budget):
    client.app.state.coordinator.stop()
    factory = client.app.state.session_factory
    run_id, _ = completed_before_tick(factory, imported["dataset_id"], budget=with_budget)
    with factory() as session:
        before = run_view(session, run_id)
    assert before["missing_modules"] == ["cards"] and before["status"] == "running"
    schedule_cards(factory)
    with factory() as session:
        assert run_view(session, run_id)["status"] == "running"  # Real queued dependency is now visible.
    with write_transaction(factory) as session:
        card = session.scalar(select(JobRow).where(JobRow.run_id == run_id, JobRow.kind == "cards"))
        card.state, card.stopped, card.result = "completed", True, {}
        if with_budget:
            run = session.get(ObjectRow, (imported["dataset_id"], "run", run_id))
            # No export context here: mark this isolated export outcome terminal, not accepted.
            run.data = {**run.data, "budget": {**run.data["budget"], "export_status": "partial"}}
    with factory() as session:
        assert run_view(session, run_id)["status"] == "completed"


@pytest.mark.parametrize("reason", ["failed_cutting", "expired_work", "failed_cards"])
def test_impossible_card_progress_is_not_eternally_running(client, imported, reason):
    client.app.state.coordinator.stop()
    factory = client.app.state.session_factory
    run_id, _ = completed_before_tick(factory, imported["dataset_id"], cards=reason == "failed_cards")
    with write_transaction(factory) as session:
        run = session.get(ObjectRow, (imported["dataset_id"], "run", run_id))
        if reason == "expired_work":
            run.data = {**run.data, "budget": {**run.data["budget"], "work_deadline_utc":
                                               (utc_now() - timedelta(seconds=1)).isoformat()}}
        else:
            job = session.scalar(select(JobRow).where(JobRow.run_id == run_id,
                JobRow.kind == ("cutting" if reason == "failed_cutting" else "cards")))
            job.state, job.result, job.stopped = "failed", None, True
    with factory() as session:
        assert run_view(session, run_id)["status"] == "partial"


@pytest.mark.parametrize("phase", ["pending", "done", "failed", "cancelled", "quick", "too_short", "expired"])
def test_only_expected_improvement_dispatch_keeps_accepted_run_polling(client, imported, phase):
    client.app.state.coordinator.stop()
    factory = client.app.state.session_factory
    run_id, refs = completed_before_tick(factory, imported["dataset_id"], cards=True)
    with write_transaction(factory) as session:
        run = session.get(ObjectRow, (imported["dataset_id"], "run", run_id))
        budget = run.data["budget"]
        if phase in {"done", "failed", "cancelled"}:
            budget = {**budget, "improvement_job_id": "recorded-attempt"}
        if phase == "quick":
            budget = {**budget, "requested_solver": {"profile": "quick", "time_limit_seconds": 30}}
        if phase == "too_short":
            budget = {**budget, "requested_solver": {"profile": "extended", "time_limit_seconds": 5}}
        if phase == "expired":
            budget = {**budget, "work_deadline_utc": (utc_now() - timedelta(seconds=1)).isoformat()}
        run.data = {**run.data, "budget": budget, "accepted_export_id": "preserved-accepted",
                    "accepted_result_refs": refs, "accepted_files": {"solution.csv": "preserved-hash"}}
    with factory() as session:
        view = run_view(session, run_id)
    assert view["status"] == ("running" if phase == "pending" else "completed")
    assert view["manifest"]["accepted_export_id"] == "preserved-accepted"
    assert view["manifest"]["accepted_files"] == {"solution.csv": "preserved-hash"}
