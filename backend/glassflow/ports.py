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
from glassflow.contracts.orders import OrderFacts, OrderReservation


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


class OrderSourcePort(Protocol):
    """U01 composition of C3 facts and C2 inventory, always in caller's UoW.

    No network, nested commit, alternate DB or cached availability. capture returns
    current canonical facts, including quote/KB/mapping and inventory revisions.
    OrderFacts.quote_customer_ref comes from C3's stored quote owner (never from
    the order's customer_ref). If Quote exposes customer_id, both must agree.
    Anonymous/unknown ownership cannot authorize bind/confirm/reserve; Pro never
    assigns or changes the customer in C3. Ownership is part of the facts hash.
    reserve is an atomic compare-and-reserve for this order/revision. Return the
    post-reservation inventory version. capture must recognize the owning order.
    Conflicts expose current remnant/version and alternatives through AppError.
    """

    def capture(self, session, dataset_id: str, quote_id: str, remnant_id: str,
                order_id: str) -> OrderFacts: ...

    def reserve(self, session, facts: OrderFacts, order_id: str,
                order_revision: int) -> OrderReservation: ...

    def reservation(self, session, dataset_id: str, reservation_id: str) -> OrderReservation: ...

    def release(self, session, reservation: OrderReservation) -> OrderReservation: ...
