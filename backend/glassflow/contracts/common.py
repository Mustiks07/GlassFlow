from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

Identifier = Annotated[str, Field(min_length=1, max_length=128)]
PositiveMm = Annotated[StrictInt, Field(gt=0)]
NonnegativeInt = Annotated[StrictInt, Field(ge=0)]
MoneyString = Annotated[str, Field(pattern=r"^\d+(?:\.\d+)?$")]


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetRequest(DTO):
    dataset_id: Identifier


class Dimensions(DTO):
    length_mm: PositiveMm
    width_mm: PositiveMm


class Evidence(DTO):
    source: str
    source_version: str
    record_id: str | None = None
    field: str | None = None


class ApiError(DTO):
    code: str
    message_ru: str
    field_errors: list[dict[str, str]] = Field(default_factory=list)
    conflict_objects: list[str] = Field(default_factory=list)
    retryable: bool = False
    correlation_id: str


class MutationRequest(DTO):
    dataset_id: Identifier
    expected_version: NonnegativeInt


class Health(DTO):
    status: Literal["ok"] = "ok"
    app: str = "GlassFlow"
    version: str = "0.1.0"


class Readiness(DTO):
    status: Literal["foundation", "ready", "degraded"]
    database: bool
    business_modules_ready: bool
