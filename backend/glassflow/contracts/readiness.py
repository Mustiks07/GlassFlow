"""Server computes buyer eligibility from pinned evidence, never from a client ID set."""

from pydantic import Field

from .common import DatasetRequest, Identifier, NonnegativeInt


class SaleReadinessRequest(DatasetRequest):
    plan_id: Identifier
    revision: NonnegativeInt
    buyer_registry_version: Identifier
    budget_seconds: float = Field(default=2, gt=0, le=30)
