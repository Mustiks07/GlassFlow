"""Public in-process boundaries. Implementations are injected by platform composition.

These are protocols, not fake business implementations. No network or DB at import time.
For semantics and ownership see docs/architecture/CONTRACTS.md.
"""

from typing import Protocol

from glassflow.contracts.cutting import Candidates, CutPlan, FindRequest, SolveInput, ValidationResult
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
