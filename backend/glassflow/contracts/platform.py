from typing import Literal

from pydantic import Field

from .common import DTO, DatasetRequest, Identifier


class Dataset(DTO):
    dataset_id: Identifier
    name: str
    mode: Literal["source", "workspace", "contest"]
    source_hashes: dict[str, str]
    row_counts: dict[str, int]


class ImportPreview(DTO):
    import_id: str
    row_counts: dict[str, int]
    errors: list[dict[str, str]]
    warnings: list[str]


class Job(DTO):
    job_id: str
    state: Literal["queued", "running", "completed", "failed", "cancelled", "interrupted"]
    stage: str
    result_ref: str | None = None
    last_valid_result_ref: str | None = None
    error_code: str | None = None


class RunRequest(DatasetRequest):
    modules: list[Literal["cutting", "assistant", "crm", "quality", "cards"]] = Field(
        default_factory=lambda: ["cutting", "assistant", "crm", "quality", "cards"]
    )
    config_version: str


class ExportResult(DTO):
    run_id: str
    status: Literal["ready", "partial", "blocked"]
    files: dict[str, str]
    errors: list[str]
