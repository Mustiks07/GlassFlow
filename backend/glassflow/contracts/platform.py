from typing import Literal

from pydantic import Field, model_validator

from .common import DTO, DatasetRequest, Identifier
from .cutting import SolverConfig


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
    kb_version: str | None = None


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
    retry_of: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    accepted_row_count: int = 0


class RunRequest(DatasetRequest):
    modules: list[Literal["cutting", "assistant", "crm", "quality", "cards"]] = Field(
        default_factory=lambda: ["cutting", "assistant", "crm", "quality", "cards"]
    )
    config_version: Identifier
    solver_config: SolverConfig = Field(default_factory=SolverConfig)
    ai_profile: Literal["direct", "judge_gateway", "local_limited"] = "local_limited"
    buyer_registry_version: str | None = None
    total_budget_seconds: int | None = Field(default=None, ge=10, le=7200, strict=True)
    export_reserve_seconds: int = Field(default=30, ge=1, le=600, strict=True)

    @model_validator(mode="after")
    def budget_reserve(self):
        if self.total_budget_seconds is not None and self.total_budget_seconds <= self.export_reserve_seconds + 5:
            raise ValueError("Whole-run budget must leave at least five working seconds besides export reserve")
        return self


class RunBudgetRenew(DatasetRequest):
    expected_version: int = Field(ge=0, strict=True)
    total_budget_seconds: int = Field(ge=10, le=7200, strict=True)
    export_reserve_seconds: int = Field(default=30, ge=1, le=600, strict=True)

    @model_validator(mode="after")
    def budget_reserve(self):
        if self.total_budget_seconds <= self.export_reserve_seconds + 5:
            raise ValueError("Whole-run budget must leave working time besides export reserve")
        return self


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
    provider: Literal["gemini", "openrouter", "basisweb"] = "gemini"
    included_quota_enabled: bool = False
    quota_token_budget: int = Field(default=1_000_000, ge=1, le=5_000_000, strict=True)
    model_id: str = Field(default="", max_length=200)
    mode: Literal["free_only", "paid_enabled"] = "free_only"
    paid_enabled: bool = False
    monthly_budget_tg: str = Field(default="0", pattern=r"^\d+(?:\.\d+)?$")
    rpm: int = Field(default=1, ge=1, le=1000, strict=True)
    tpm: int = Field(default=1000, ge=1, le=10_000_000, strict=True)
    rpd: int = Field(default=100, ge=1, le=1_000_000, strict=True)
    max_parallel: int = Field(default=1, ge=1, le=8, strict=True)
    timeout_seconds: int = Field(default=30, ge=1, le=120, strict=True)
    max_retries: int = Field(default=2, ge=0, le=2, strict=True)
    max_tool_iterations: int = Field(default=6, ge=1, le=6, strict=True)
    max_output_tokens: int = Field(default=2048, ge=1, le=32768, strict=True)
    fallback_models: list[str] = Field(default_factory=list, max_length=3)
    gateway_url: str | None = None
    secret_present: bool = False


class SettingsUpdate(AISettings):
    api_key: str | None = Field(default=None, max_length=4096, exclude=True, repr=False)


class RestoreRequest(DTO):
    backup_id: str
    confirm_replace: bool


class KbHead(DatasetRequest):
    kb_version: str
    sha256: str
    version: int


class LocalSession(DTO):
    session_token: str


class RunView(DTO):
    manifest: dict
    status: Literal["running", "completed", "partial", "blocked"]
    jobs: list[Job]
    missing_modules: list[str]
    version: int = 0
    budget: dict | None = None
