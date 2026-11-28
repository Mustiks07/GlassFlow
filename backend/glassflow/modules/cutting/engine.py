"""Worker-side engine implementing ``glassflow.ports.CuttingPort``.

``CuttingEngine.solve(SolveInput, JobContext) -> CutPlan`` is a pure function of a serialisable
snapshot: no DB, no network. The platform worker calls it; the coordinator persists the result with
``CuttingService.store_solver_plan``. Incumbents are published only after independent validation.
Cancellation keeps the last valid incumbent (never a partially built plan).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import time
from collections.abc import Callable

from glassflow.contracts.cutting import (
    Candidates,
    CutPlan,
    FindRequest,
    SolveInput,
    SolverConfig,
    ValidationResult,
)

from .conversion import snapshot_from_input, to_assignment, to_placement, to_plan_issue
from .domain import NEW, Assignment, Snapshot
from .geometry import validate_plan
from .metrics import compute_metrics
from .solver import CuttingSolver, SolveOutcome, SolverSettings

ENGINE_VERSION = "cutting-engine/1.1-min-free-incumbent"


def default_workers() -> int:
    """TZ 27: initial thread limit max(1, CPU-1); the platform may pass a lower value."""
    return max(1, (os.cpu_count() or 2) - 1)


def input_hash(data: SolveInput) -> str:
    payload = data.model_dump(mode="json", exclude={"config"})
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class _Bridge:
    def __init__(self, context, to_plan: Callable[[SolveOutcome], CutPlan]):
        self.context = context
        self.to_plan = to_plan

    def cancelled(self) -> bool:
        return bool(self.context is not None and self.context.cancelled())

    def progress(self, stage: str, completed: int, total: int | None) -> None:
        if self.context is not None:
            self.context.progress(stage, completed, total)

    def incumbent(self, outcome: SolveOutcome) -> None:
        if self.context is None:
            return
        plan = self.to_plan(outcome)
        # Only a plan valid for the ORIGINAL task (including every requested lock) is published.
        required_free = plan.config.minimum_free_remnants if plan.config is not None else 0
        if (plan.status == "validated" and plan.metrics.free_original_remnants >= required_free
                and plan.evidence.get('minimum_free_remnants_met') is True):
            self.context.incumbent(plan)


class CuttingEngine:
    def solve(self, snapshot: SolveInput, context=None) -> CutPlan:
        started = time.perf_counter()
        full = self._normalise(snapshot_from_input(snapshot), set(snapshot.unavailable_remnant_ids))
        config = snapshot.config
        settings = SolverSettings(
            profile=config.profile, seed=config.seed, time_limit_seconds=float(config.time_limit_seconds),
            workers=1 if config.fixed_work else config.workers, minimum_free_remnants=config.minimum_free_remnants,
            fixed_work=config.fixed_work, max_pool_patterns=config.max_pool_patterns)
        occupied = set(snapshot.occupied_remnant_ids)
        locks = [to_assignment(p) for p in snapshot.locks]
        kept = [lk for lk in locks if lk.remnant_id in occupied]  # production-fixed pieces stay exactly as they are
        active_locks = [lk for lk in locks if lk.remnant_id not in occupied]
        reduced = self._reduced(full, {lk.part_id for lk in kept}, occupied)
        unavailable = set(snapshot.unavailable_remnant_ids) - occupied
        previous = {p.part_id: to_assignment(p) for p in snapshot.previous_placements}
        meta = {
            "engine": ENGINE_VERSION,
            "input_sha256": input_hash(snapshot),
            "python": platform.python_version(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count() or 0,
            "kept_parts": len(kept),
            "occupied_remnants": len(occupied),
            "base_plan_id": snapshot.base_plan_id,
            "base_revision": snapshot.base_revision,
        }

        def to_plan(outcome: SolveOutcome) -> CutPlan:
            merged = dict(outcome.assignments)
            for lk in kept:
                merged[lk.part_id] = Assignment(lk.part_id, lk.remnant_id, lk.x_mm, lk.y_mm, lk.rot, "placement")
            return self._plan(full, snapshot, config, outcome, merged, unavailable, meta, started)

        solver = CuttingSolver(reduced, settings, unavailable=unavailable, occupied=occupied, locks=active_locks,
                               previous=previous, callbacks=_Bridge(context, to_plan))
        outcome = solver.run()
        return to_plan(outcome)

    @staticmethod
    def _normalise(full: Snapshot, unavailable: set[str]) -> Snapshot:
        """A piece reserved by the plan being replanned is usable; others are in ``unavailable``."""
        from dataclasses import replace

        remnants = {rid: (replace(r, status="available") if r.status == "reserved" and rid not in unavailable else r)
                    for rid, r in full.remnants.items()}
        return Snapshot(full.dataset_id, full.materials, remnants, full.parts, full.part_order, full.remnant_order)

    @staticmethod
    def _reduced(full: Snapshot, kept_parts: set[str], occupied: set[str]) -> Snapshot:
        if not kept_parts and not occupied:
            return full
        parts = {pid: p for pid, p in full.parts.items() if pid not in kept_parts}
        remnants = {rid: r for rid, r in full.remnants.items() if rid not in occupied}
        return Snapshot(full.dataset_id, full.materials, remnants, parts,
                        [p for p in full.part_order if p in parts], [r for r in full.remnant_order if r in remnants])

    @staticmethod
    def _plan(full: Snapshot, data: SolveInput, config: SolverConfig, outcome: SolveOutcome,
              merged: dict[str, Assignment], unavailable: set[str], meta: dict, started: float) -> CutPlan:
        rows = [merged.get(pid, Assignment(pid, NEW)) for pid in full.part_order]
        requested = [to_assignment(p) for p in data.locks]
        # Validate against the ORIGINAL task: every requested lock, not only the ones the solver satisfied.
        # A geometrically valid alternative that breaks a lock is returned as ``invalid`` with LOCK_* issues,
        # i.e. a proposal for the manager, never a validated solution of the requested task.
        report = validate_plan(full, rows, unavailable_remnant_ids=unavailable,
                               locks=requested + [a for a in rows if a.lock_kind != "none"])
        metrics, free = compute_metrics(full, report, outcome.new_reasons)
        status = "validated" if report.valid else "invalid"
        evidence = dict(meta)
        evidence.update({k: v for k, v in outcome.stats.items() if isinstance(v, (str, int, float, bool)) or v is None})
        evidence["wall_seconds"] = round(time.perf_counter() - started, 3)
        evidence["stage"] = outcome.stage
        evidence['minimum_free_remnants_met'] = (outcome.meets_min_free and
            metrics.free_original_remnants >= config.minimum_free_remnants)
        lock_issues = [to_plan_issue(c) for c in outcome.conflicts]
        return CutPlan(
            dataset_id=data.dataset_id, plan_id="unsaved", revision=0, status=status,
            placements=[to_placement(a) for a in rows], metrics=metrics, free_original_remnant_ids=free,
            # A heuristic that missed a lock is not a proof of infeasibility: keep the real search status.
            search_status=outcome.search_status, stop_reason=outcome.stop_reason,
            config=config, issues=[to_plan_issue(i) for i in report.issues] + lock_issues, evidence=evidence,
            parent_plan_id=data.base_plan_id, parent_revision=data.base_revision, requested_locks=list(data.locks))

    def validate(self, snapshot: SolveInput, plan: CutPlan) -> ValidationResult:
        full = snapshot_from_input(snapshot)
        if plan.dataset_id != snapshot.dataset_id:
            return ValidationResult(valid=False, errors=["DATASET_MISMATCH:__plan__: план другого набора данных"],
                                    invalid_part_ids=[], missing_part_ids=[])
        report = validate_plan(full, [to_assignment(p) for p in plan.placements],
                               unavailable_remnant_ids=snapshot.unavailable_remnant_ids,
                               locks=[to_assignment(p) for p in snapshot.locks])
        return ValidationResult(valid=report.valid, errors=[i.as_text() for i in report.issues],
                                invalid_part_ids=report.invalid_part_ids, missing_part_ids=report.missing_part_ids,
                                issues=[to_plan_issue(i) for i in report.issues], plan_revision=plan.revision)

    def find_candidates(self, request: FindRequest) -> Candidates:  # pragma: no cover - needs inventory
        raise NotImplementedError("find_candidates needs inventory state: use CuttingPortAdapter")


class CuttingPortAdapter(CuttingEngine):
    """CuttingPort for in-process consumers (AI tools, sales): DB-backed candidate search, pure solve."""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    def find_candidates(self, request: FindRequest) -> Candidates:
        from .service import CuttingService

        with self.session_factory() as session:
            return CuttingService(session).find_candidates(request)
