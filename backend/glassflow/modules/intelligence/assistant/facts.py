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


@dataclass(frozen=True)
class QuoteTotal:
    """A calculated quote with several lines: naming a line without the total is incomplete."""

    lines: tuple[Decimal, ...]
    total: Decimal


@dataclass
class FactSet:
    facts: list[Fact] = field(default_factory=list)
    # Complete claims rendered by trusted domain code, including subject, role,
    # unit, quantity and source version. LLM may select a reference, never edit it.
    commercial_claims: dict[str, str] = field(default_factory=dict)
    quotes: list[QuoteTotal] = field(default_factory=list)

    def claim(self, text: str, key: str | None = None, source_ref: str = "renderer:domain") -> str:
        key = key or f"c{len(self.commercial_claims) + 1}"
        self.commercial_claims[key] = text
        self.facts.append(Fact(f"f{len(self.facts) + 1}", "rendered_claim", text, None, source_ref))
        return f"[[{key}]]"

    def render(self, text: str) -> str:
        for key, claim in self.commercial_claims.items():
            text = text.replace(f"[[{key}]]", claim)
        return text

    def add_quote(self, lines, total: Decimal) -> None:
        amounts = tuple(Decimal(amount) for amount in lines)
        if len(amounts) > 1:
            self.quotes.append(QuoteTotal(amounts, Decimal(total)))

    def add(self, kind: str, value, unit: str | None, source_ref: str) -> Fact:
        numeric = value if isinstance(value, Decimal) else None
        if isinstance(value, int) and not isinstance(value, bool):
            numeric = Decimal(value)
        fact = Fact(f"f{len(self.facts) + 1}", kind, str(value), unit, source_ref, numeric)
        self.facts.append(fact)
        if kind == "rendered_claim" and source_ref.startswith("renderer:"):
            self.commercial_claims[f"restored{len(self.commercial_claims)}"] = str(value)
        return fact

    def numbers(self) -> set[Decimal]:
        return {fact.numeric for fact in self.facts if fact.numeric is not None}

    def extend(self, other: "FactSet") -> None:
        for fact in other.facts:
            self.add(fact.kind, fact.numeric if fact.numeric is not None else fact.value, fact.unit, fact.source_ref)
        self.quotes.extend(other.quotes)
