"""Ports this module *consumes* from neighbours. Implementations are injected by composition.

- InventoryPort: Claude 2 inventory/cutting ``find_candidates`` (read-only, never reserves).
- CrmPort: GPT Pro CRM ranking and local reminder drafts (no outbound messages).
- ScenarioPort: Claude 2 / platform jobs for "what-if" comparisons (never applies a scenario).

When a port is not wired the tools report ``service_unavailable`` honestly; release code never
substitutes a fixture. Test doubles live in tests/intelligence only.
"""

from __future__ import annotations

from typing import Protocol

from glassflow.contracts.crm import Ranking, RankRequest, Reminder, ReminderRequest
from glassflow.contracts.cutting import Candidates, FindRequest


class InventoryPort(Protocol):
    def find_candidates(self, request: FindRequest) -> Candidates: ...


class CrmPort(Protocol):
    def rank(self, request: RankRequest) -> Ranking: ...

    def draft_reminder(self, request: ReminderRequest) -> Reminder: ...


class ScenarioPort(Protocol):
    def compare(self, dataset_id: str, base_plan_id: str, change: dict[str, object]) -> dict[str, object]: ...


class ServiceUnavailable(RuntimeError):
    """A neighbouring domain service is not wired or failed; never replaced by fake data."""

    def __init__(self, service: str, detail: str = ""):
        super().__init__(f"{service} unavailable: {detail}" if detail else f"{service} unavailable")
        self.service = service
