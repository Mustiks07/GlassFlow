from typing import Literal

from pydantic import Field

from .common import DTO, DatasetRequest, Identifier


class Dataset(DTO):
    dataset_id: Identifier
    name: str
    mode: Literal["source", "workspace", "contest"]
    source_hashes: dict[str, str]
    row_counts: dict[str, int]
    parent_id: str | None = None
    version: int = 0
    created_at: str | None = None
    schema_version: str = "1"


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
    run_id: str | None = None
    dataset_id: str | None = None
    cancel_requested: bool = False
    stopped: bool = False
    completed: int = 0
    total: int | None = None
    result: dict | None = None
    last_valid_result: dict | None = None


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


class ImportCommit(DTO):
    name: str = Field(default="Набор данных", min_length=1, max_length=200)
    mode: Literal["source", "contest"] = "source"
    explicit_copy: bool = False


class WorkingCopy(DTO):
    name: str = Field(default="Рабочая копия", min_length=1, max_length=200)


class VersionAction(DatasetRequest):
    expected_version: int = Field(ge=0, strict=True)


class AISettings(DTO):
    version: int = Field(default=0, ge=0, strict=True)
    profile: Literal["direct", "judge_gateway", "local_limited"] = "local_limited"
    provider: Literal["gemini", "openrouter"] = "gemini"
    model_id: str = Field(default="", max_length=200)
    mode: Literal["free_only", "paid_enabled"] = "free_only"
    paid_enabled: bool = False
    monthly_budget_tg: str = Field(default="0", pattern=r"^\d+(?:\.\d+)?$")
    rpm: int = Field(default=1, ge=1, le=1000, strict=True)
    max_parallel: int = Field(default=1, ge=1, le=8, strict=True)
    timeout_seconds: int = Field(default=30, ge=1, le=120, strict=True)
    max_retries: int = Field(default=2, ge=0, le=2, strict=True)
    gateway_url: str | None = None
    secret_present: bool = False


class SettingsUpdate(AISettings):
    api_key: str | None = Field(default=None, max_length=4096, exclude=True)


class RestoreRequest(DTO):
    backup_id: str
    confirm_replace: bool
