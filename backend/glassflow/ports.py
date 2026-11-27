"""Public in-process boundaries. Implementations are injected by platform composition.

These are protocols, not fake business implementations. No network or DB at import time.
For semantics and ownership see docs/architecture/CONTRACTS.md.
"""

from typing import Protocol

from glassflow.contracts.cutting import (
    Candidates,
    CutPlan,
    FindRequest,
    Remnant,
    SolveInput,
    ValidationResult,
)
from glassflow.contracts.intelligence import DialogRequest, DialogVerdict, Quote, QuoteRequest


class JobContext(Protocol):
    def cancelled(self) -> bool: ...

    def progress(self, stage: str, completed: int, total: int | None) -> None: ...

    def incumbent(self, plan: CutPlan) -> None: ...


class CuttingPort(Protocol):
    def solve(self, snapshot: SolveInput, context: JobContext) -> CutPlan: ...

    def validate(self, snapshot: SolveInput, plan: CutPlan) -> ValidationResult: ...

    def find_candidates(self, request: FindRequest) -> Candidates: ...


class IntelligencePort(Protocol):
    def quote(self, request: QuoteRequest) -> Quote: ...

    async def check_dialog(self, request: DialogRequest) -> DialogVerdict: ...


class UnitOfWork(Protocol):
    """Platform supplies one transaction; feature services must not commit nested transactions."""

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class SalesSourcePort(Protocol):
    """Additive platform seam for C2; uses caller transaction, never nested commit.

    get_plan returns the CURRENT selected revision, not an arbitrary historical revision.
    validate_plan calls C2's independent validator; original membership comes from source records.
    """

    def get_plan(self, session, dataset_id: str, plan_id: str) -> CutPlan: ...

    def validate_plan(self, session, dataset_id: str, plan: CutPlan) -> ValidationResult: ...

    def get_remnant(self, session, dataset_id: str, remnant_id: str) -> Remnant: ...
