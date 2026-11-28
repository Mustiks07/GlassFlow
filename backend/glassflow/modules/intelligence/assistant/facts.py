"""Typed verified facts. Every number shown to a client must come from one of these."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class Fact:
    fact_id: str
    kind: str  # price | line | total | measure | rule | unknown | remnant | dimension | quantity
    value: str
    unit: str | None
    source_ref: str
    numeric: Decimal | None = None


@dataclass
class FactSet:
    facts: list[Fact] = field(default_factory=list)

    def add(self, kind: str, value, unit: str | None, source_ref: str) -> Fact:
        numeric = value if isinstance(value, Decimal) else None
        if isinstance(value, int) and not isinstance(value, bool):
            numeric = Decimal(value)
        fact = Fact(f"f{len(self.facts) + 1}", kind, str(value), unit, source_ref, numeric)
        self.facts.append(fact)
        return fact

    def numbers(self) -> set[Decimal]:
        return {fact.numeric for fact in self.facts if fact.numeric is not None}

    def extend(self, other: "FactSet") -> None:
        for fact in other.facts:
            self.add(fact.kind, fact.numeric if fact.numeric is not None else fact.value, fact.unit, fact.source_ref)
