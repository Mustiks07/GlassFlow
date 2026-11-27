from fastapi import APIRouter

from glassflow.contracts.common import ApiError
from glassflow.contracts.crm import ManagerMetrics, Ranking, RankRequest, Reminder, ReminderRequest
from glassflow.core.errors import FeatureUnavailable

router = APIRouter(tags=["crm"], responses={501: {"model": ApiError}})


@router.post("/crm/rank", response_model=Ranking)
def rank_applications(request: RankRequest):
    raise FeatureUnavailable("crm.rank_applications")


@router.get("/crm/reminders", response_model=list[Reminder])
def list_reminders(dataset_id: str):
    raise FeatureUnavailable("crm.list_reminders")


@router.post("/crm/reminders", response_model=Reminder)
def create_reminder(request: ReminderRequest):
    raise FeatureUnavailable("crm.create_reminder")


@router.get("/analytics/managers", response_model=list[ManagerMetrics])
def manager_metrics(dataset_id: str):
    raise FeatureUnavailable("crm.manager_metrics")
