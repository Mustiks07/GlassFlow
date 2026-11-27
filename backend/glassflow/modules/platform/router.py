from fastapi import APIRouter, File, UploadFile

from glassflow.contracts.common import ApiError
from glassflow.contracts.platform import Dataset, ExportResult, ImportPreview, Job, RunRequest
from glassflow.core.errors import FeatureUnavailable

router = APIRouter(tags=["platform"], responses={501: {"model": ApiError}})


@router.get("/datasets", response_model=list[Dataset])
def list_datasets():
    raise FeatureUnavailable("platform.list_datasets")


@router.get("/datasets/{dataset_id}", response_model=Dataset)
def get_dataset(dataset_id: str):
    raise FeatureUnavailable("platform.get_dataset")


@router.post("/imports/preview", response_model=ImportPreview)
def preview_import(file: UploadFile = File(...)):
    raise FeatureUnavailable("platform.preview_import")


@router.post("/imports/{import_id}/commit", response_model=Dataset)
def commit_import(import_id: str):
    raise FeatureUnavailable("platform.commit_import")


@router.post("/runs", response_model=Job)
def create_run(request: RunRequest):
    raise FeatureUnavailable("platform.create_run")


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: str):
    raise FeatureUnavailable("platform.get_job")


@router.post("/jobs/{job_id}/cancel", response_model=Job)
def cancel_job(job_id: str):
    raise FeatureUnavailable("platform.cancel_job")


@router.post("/runs/{run_id}/export", response_model=ExportResult)
def export_run(run_id: str):
    raise FeatureUnavailable("platform.export_run")
