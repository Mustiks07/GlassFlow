"""N02 persisted UTC budgets; monotonic deadlines are reconstructed within each process."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from glassflow.core.errors import AppError


def utc_now():
    return datetime.now(UTC)


def create_budget(total_seconds, reserve_seconds, solver, version=0):
    start = utc_now()
    return {"version": version, "total_seconds": total_seconds, "export_reserve_seconds": reserve_seconds,
            "started_at": start.isoformat(), "deadline_utc": (start + timedelta(seconds=total_seconds)).isoformat(),
            "work_deadline_utc": (start + timedelta(seconds=total_seconds - reserve_seconds)).isoformat(),
            "requested_solver": deepcopy(solver), "phase": "baseline", "export_status": "not_started"}


def remaining(budget, *, work=False):
    if not budget:
        return None
    end = datetime.fromisoformat(budget["work_deadline_utc" if work else "deadline_utc"])
    return max(0.0, (end - utc_now()).total_seconds())


def budget_view(budget):
    if not budget:
        return None
    return {**budget, "remaining_seconds": remaining(budget), "work_remaining_seconds": remaining(budget, work=True),
            "deadline_met": None if budget.get("baseline_accepted_at") is None else
                datetime.fromisoformat(budget["baseline_accepted_at"]) <= datetime.fromisoformat(budget["deadline_utc"])}


def require_work_time(budget):
    if budget and remaining(budget, work=True) <= 0:
        raise AppError(409, "RUN_BUDGET_EXPIRED", "Рабочее время прогона истекло; новый бюджет задается явно.")


def bound_solver(config, budget, *, baseline=False):
    if not budget:
        return deepcopy(config)
    require_work_time(budget)
    result = deepcopy(config)
    seconds = max(1, int(remaining(budget, work=True) - 2))
    result["time_limit_seconds"] = min(result.get("time_limit_seconds", 5), seconds, 5 if baseline else 3600)
    if baseline:
        result["profile"] = "quick"
    return result
