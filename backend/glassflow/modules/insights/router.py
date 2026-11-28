from fastapi import APIRouter, Request

from glassflow.contracts.insights import AnalyticsAnswer, AnalyticsQuestion, ComparableRequest, ComparableView

from . import comparable

router = APIRouter(tags=['insights'])


@router.post('/analytics/comparable', response_model=ComparableView)
def compare_managers(body: ComparableRequest, request: Request):
    with request.app.state.session_factory() as session:
        return comparable.compare(session, body)


@router.post('/analytics/questions', response_model=AnalyticsAnswer)
def analytics_question(body: AnalyticsQuestion, request: Request):
    with request.app.state.session_factory() as session:
        return comparable.answer(session, body)
