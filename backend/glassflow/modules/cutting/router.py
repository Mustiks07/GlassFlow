from fastapi import APIRouter

from glassflow.contracts.common import ApiError
from glassflow.contracts.cutting import (
    Candidates,
    CommitPlan,
    CutPlan,
    FindRequest,
    NewRemnant,
    Remnant,
    SolveRequest,
    ValidationResult,
)
from glassflow.contracts.platform import Job
from glassflow.core.errors import FeatureUnavailable

router = APIRouter(tags=["cutting"], responses={501: {"model": ApiError}})


@router.get("/remnants", response_model=list[Remnant])
def list_remnants(dataset_id: str):
    raise FeatureUnavailable("cutting.list_remnants")


@router.post("/remnants", response_model=Remnant)
def add_remnant(request: NewRemnant):
    raise FeatureUnavailable("cutting.add_remnant")


@router.post("/cutting/candidates", response_model=Candidates)
def find_candidates(request: FindRequest):
    raise FeatureUnavailable("cutting.find_candidates")


@router.post("/cutting/solve", response_model=Job)
def solve(request: SolveRequest):
    raise FeatureUnavailable("cutting.solve")


@router.get("/plans/{plan_id}", response_model=CutPlan)
def get_plan(plan_id: str, dataset_id: str):
    raise FeatureUnavailable("cutting.get_plan")


@router.post("/plans/{plan_id}/validate", response_model=ValidationResult)
def validate_plan(plan_id: str, dataset_id: str):
    raise FeatureUnavailable("cutting.validate_plan")


@router.post("/plans/{plan_id}/commit", response_model=CutPlan)
def commit_plan(plan_id: str, request: CommitPlan):
    raise FeatureUnavailable("cutting.commit_plan")
