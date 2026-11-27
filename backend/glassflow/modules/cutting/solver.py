"""Cutting optimiser: exact tempered matching + heuristic portfolio + pattern pool MILP + CP-SAT.

Pipeline (TZ section 12):
  eligibility -> tempered max-weight matching -> several Guillotine/MaxRects greedy orders (fast
  incumbent) -> pool of concrete per-remnant layouts -> SciPy ``milp`` (HiGHS) set packing with the
  "five fully free original remnants" constraint -> column generation (LP duals priced by packing
  heuristics and by exact single-remnant CP-SAT) and CP-SAT LNS on small sub-problems -> lexicographic
  secondary objective -> independent validation.

Attribution: the greedy families and the "pool + set-packing MIP" idea come from the team research
prototype ``analysis/cutting/research.py`` / ``patterns.py`` (re-implemented here; the research CSV
outputs are never read). Pool optimality is never reported as global optimality.

The solver is a pure function of a serialisable snapshot. It never touches the database; progress,
incumbents and cancellation go through callbacks supplied by the platform worker.
"""

from __future__ import annotations

import random
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from .domain import GAP_MM, NEW, TRIM_MM, Assignment, Snapshot, oriented_size
from .eligibility import build_eligibility, pair_reason
from .geometry import Issue, validate_plan
from .packing import HEURISTICS, SPLITS, Item, MaxRectsBin, make_bin

# --------------------------------------------------------------------------------------------- config

PROFILES: dict[str, dict] = {
    # greedy: number of global greedy runs; fills: random single-remnant fills per remnant;
    # rounds: column generation rounds; cpsat: exact pricing / LNS enabled.
    "quick": {"greedy": 24, "fills": 0, "rounds": 0, "cpsat": False, "lns": 0, "patience": 0},
    "standard": {"greedy": 240, "fills": 24, "rounds": 25, "cpsat": True, "lns": 20, "patience": 3},
    "extended": {"greedy": 800, "fills": 80, "rounds": 400, "cpsat": True, "lns": 400, "patience": 12},
}


@dataclass(slots=True)
class SolverSettings:
    profile: str = "standard"
    seed: int = 42
    time_limit_seconds: float = 60.0
    workers: int = 1
    minimum_free_remnants: int = 5
    fixed_work: bool = False
    """Deterministic regression mode: work counters only, single thread, deterministic CP-SAT time."""
    max_pool_patterns: int = 80_000
    first_plan_seconds: float = 5.0
    pricing_seconds: float | None = None
    """CP-SAT budget per exact pricing call (deterministic time units when ``fixed_work``); None = profile default."""
    lns_seconds: float | None = None
    """CP-SAT budget per LNS repair; None = profile default."""


class SolverCallbacks(Protocol):
    def cancelled(self) -> bool: ...

    def progress(self, stage: str, completed: int, total: int | None) -> None: ...

    def incumbent(self, outcome: SolveOutcome) -> None: ...


class _NullCallbacks:
    def cancelled(self) -> bool:
        return False

    def progress(self, stage: str, completed: int, total: int | None) -> None:
        return None

    def incumbent(self, outcome: SolveOutcome) -> None:
        return None


# --------------------------------------------------------------------------------------------- model


@dataclass(frozen=True, slots=True)
class Pattern:
    remnant_id: str
    placements: tuple[tuple[str, int, int, int], ...]  # (part_id, x, y, rot), sorted by part_id
    area: int

    @property
    def part_ids(self) -> tuple[str, ...]:
        return tuple(p[0] for p in self.placements)


@dataclass(slots=True)
class SolveOutcome:
    assignments: dict[str, Assignment]
    """Only covered parts; every other part of the snapshot is NEW."""
    covered_area: int
    full_orders: int
    free_original: int
    meets_min_free: bool
    locks_satisfied: int = 0
    search_status: str = "feasible"
    stop_reason: str = "completed"
    stage: str = "first_plan"
    elapsed_seconds: float = 0.0
    stats: dict = field(default_factory=dict)
    conflicts: list[Issue] = field(default_factory=list)
    new_reasons: dict[str, str] = field(default_factory=dict)

    def rows(self, snapshot: Snapshot) -> list[Assignment]:
        return [self.assignments.get(pid, Assignment(pid, NEW)) for pid in snapshot.part_order]


class PatternPool:
    def __init__(self, max_patterns: int):
        self.patterns: list[Pattern] = []
        self._keys: set[tuple[str, frozenset[str]]] = set()
        self.max_patterns = max_patterns
        self.full = False

    def __len__(self) -> int:
        return len(self.patterns)

    def add(self, pattern: Pattern) -> bool:
        if not pattern.placements:
            return False
        key = (pattern.remnant_id, frozenset(pattern.part_ids))
        if key in self._keys:
            return False
        if len(self.patterns) >= self.max_patterns:
            self.full = True
            return False
        self._keys.add(key)
        self.patterns.append(pattern)
        return True

    def contains(self, remnant_id: str, part_ids: Iterable[str]) -> bool:
        return (remnant_id, frozenset(part_ids)) in self._keys


# --------------------------------------------------------------------------------------------- solver


class _Problem:
    """Pre-processed snapshot: eligibility, locks, groups. Pure data, no DB."""

    def __init__(
        self,
        snapshot: Snapshot,
        settings: SolverSettings,
        unavailable: set[str],
        occupied: set[str],
        locks: list[Assignment],
        previous: dict[str, Assignment] | None,
    ):
        self.s = snapshot
        self.settings = settings
        self.available = [
            rid
            for rid in snapshot.remnant_order
            if rid not in unavailable and rid not in occupied and snapshot.remnants[rid].status == "available"
        ]
        available_set = set(self.available)
        self.elig = build_eligibility(snapshot, available_set, occupied)
        self.previous = previous or {}
        self.conflicts: list[Issue] = []
        self.lock_remnant: dict[str, str] = {}  # part -> remnant
        self.fixed_place: dict[str, dict[str, tuple[int, int, int]]] = defaultdict(dict)  # remnant -> part -> xyr
        self.required: dict[str, set[str]] = defaultdict(set)  # remnant -> locked parts
        for lock in locks:
            if lock.lock_kind == "none":
                continue
            part = snapshot.parts.get(lock.part_id)
            remnant = snapshot.remnants.get(lock.remnant_id)
            if part is None or remnant is None or lock.remnant_id not in available_set:
                self.conflicts.append(
                    Issue(
                        "LOCK_CONFLICT",
                        f"Закрепление {lock.part_id} → {lock.remnant_id} недоступно: деталь или остаток "
                        "отсутствует, исключен или занят.",
                        lock.part_id,
                        lock.remnant_id,
                    )
                )
                continue
            reason = pair_reason(snapshot, part, remnant)
            if reason is not None:
                self.conflicts.append(
                    Issue("LOCK_CONFLICT", f"Закрепление {lock.part_id} → {lock.remnant_id}: {reason}.",
                          lock.part_id, lock.remnant_id)
                )
                continue
            self.lock_remnant[lock.part_id] = lock.remnant_id
            self.required[lock.remnant_id].add(lock.part_id)
            if lock.lock_kind == "placement" and not snapshot.is_tempered(part.material_id):
                if lock.x_mm is None or lock.y_mm is None or lock.rot is None:
                    self.conflicts.append(Issue("LOCK_CONFLICT", "Закрепление размещения без координат.",
                                                lock.part_id, lock.remnant_id))
                    continue
                self.fixed_place[lock.remnant_id][lock.part_id] = (lock.x_mm, lock.y_mm, lock.rot)
        # Restrict eligibility of locked parts to their remnant.
        for pid, rid in self.lock_remnant.items():
            self.elig.eligible[pid] = [rid] if rid in self.elig.eligible.get(pid, []) else []
        self.by_remnant: dict[str, list[str]] = defaultdict(list)
        for pid in snapshot.part_order:
            for rid in self.elig.eligible[pid]:
                self.by_remnant[rid].append(pid)
        self.materials = sorted({snapshot.parts[p].material_id for p in snapshot.part_order})
        self.tempered_parts = [p for p in snapshot.part_order if snapshot.is_tempered(snapshot.parts[p].material_id)]
        self.ordinary_parts = [
            p for p in snapshot.part_order if not snapshot.is_tempered(snapshot.parts[p].material_id)
        ]
        self.original_available = [rid for rid in self.available if snapshot.remnants[rid].original]
        self.orders: dict[str, list[str]] = defaultdict(list)
        for pid in snapshot.part_order:
            self.orders[snapshot.parts[pid].order_id].append(pid)
        max_age = max((snapshot.remnants[r].age_days or 0 for r in self.available), default=0)
        self.max_age = max_age

    # -- pattern helpers -----------------------------------------------------------------------
    def pattern_from_bin(self, rid: str, placed: list[tuple[int, int, int, int]], keys: list[str]) -> Pattern:
        placements = tuple(sorted((keys[k], x, y, rot) for k, x, y, rot in placed))
        area = sum(self.s.parts[p[0]].area for p in placements)
        return Pattern(rid, placements, area)

    def pattern_ok_for_locks(self, pattern: Pattern) -> bool:
        required = self.required.get(pattern.remnant_id)
        if required and not required.issubset(pattern.part_ids):
            return False
        fixed = self.fixed_place.get(pattern.remnant_id)
        if fixed:
            got = {p[0]: (p[1], p[2], p[3]) for p in pattern.placements}
            if any(got.get(pid) != xyr for pid, xyr in fixed.items()):
                return False
        for pid in pattern.part_ids:
            lock = self.lock_remnant.get(pid)
            if lock is not None and lock != pattern.remnant_id:
                return False
        return True

    def new_bin(self, rid: str, kind: str, heuristic: str, split: str, keys: list[str]):
        remnant = self.s.remnants[rid]
        fixed = self.fixed_place.get(rid)
        if fixed:
            bin_ = MaxRectsBin(remnant.length_mm, remnant.width_mm, heuristic if heuristic in HEURISTICS else "bssf")
            for pid, (x, y, rot) in fixed.items():
                w, h = oriented_size(self.s.parts[pid], rot)
                keys.append(pid)
                bin_.insert_at(len(keys) - 1, x, y, w + GAP_MM, h + GAP_MM, rot)
            return bin_
        return make_bin(kind, remnant.length_mm, remnant.width_mm, heuristic, split)


def _ordered(parts: list[str], snapshot: Snapshot, rng: random.Random, run: int, value=None) -> list[str]:
    def base(pid: str) -> float:
        return value(pid) if value else snapshot.parts[pid].area

    if run == 0:
        return sorted(parts, key=lambda p: (-base(p), p))
    mode = run % 4
    if mode == 0:
        return sorted(parts, key=lambda p: -base(p) * rng.uniform(0.55, 1.6))
    if mode == 1:
        return sorted(parts, key=lambda p: -max(snapshot.parts[p].length_mm, snapshot.parts[p].width_mm)
                      * rng.uniform(0.7, 1.4))
    if mode == 2:
        return sorted(parts, key=lambda p: -(snapshot.parts[p].length_mm + snapshot.parts[p].width_mm)
                      * rng.uniform(0.7, 1.4))
    shuffled = list(parts)
    rng.shuffle(shuffled)
    shuffled.sort(key=lambda p: -base(p) * rng.uniform(0.3, 2.5))
    return shuffled


class CuttingSolver:
    def __init__(
        self,
        snapshot: Snapshot,
        settings: SolverSettings | None = None,
        *,
        unavailable: Iterable[str] = (),
        occupied: Iterable[str] = (),
        locks: Iterable[Assignment] = (),
        previous: dict[str, Assignment] | None = None,
        callbacks: SolverCallbacks | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ):
        self.settings = settings or SolverSettings()
        if self.settings.profile not in PROFILES:
            raise ValueError(f"unknown profile {self.settings.profile}")
        self.unavailable = set(unavailable)
        self.occupied = set(occupied)
        self.locks = list(locks)
        self.p = _Problem(snapshot, self.settings, self.unavailable, self.occupied, self.locks, previous)
        self.s = snapshot
        self.cb = callbacks or _NullCallbacks()
        self.clock = clock
        self.rng = random.Random(self.settings.seed)
        self.pool = PatternPool(self.settings.max_pool_patterns)
        self.best: SolveOutcome | None = None
        self.best_unconstrained: SolveOutcome | None = None
        self.stats: dict = defaultdict(int)
        self.stop_reason = "completed"
        self.started = 0.0
        self.profile = PROFILES[self.settings.profile]

    # -- budget -------------------------------------------------------------------------------
    def elapsed(self) -> float:
        return self.clock() - self.started

    def should_stop(self, reserve: float = 0.0) -> bool:
        if self.cb.cancelled():
            self.stop_reason = "cancelled"
            return True
        if self.elapsed() + reserve >= self.settings.time_limit_seconds:
            self.stop_reason = "time_limit"
            return True
        return False

    # -- evaluation ---------------------------------------------------------------------------
    def evaluate(self, assignments: dict[str, Assignment], stage: str) -> SolveOutcome | None:
        report = validate_plan(
            self.s,
            [assignments.get(pid, Assignment(pid, NEW)) for pid in self.s.part_order],
            unavailable_remnant_ids=self.unavailable | self.occupied,
        )
        if not report.valid:
            self.stats["rejected_invalid_candidates"] += 1
            return None
        area = sum(self.s.parts[pid].area for pid in report.ok_part_ids)
        used = set(report.ok_part_ids.values())
        free_original = sum(1 for rid in self.p.original_available if rid not in used)
        covered = set(report.ok_part_ids)
        full_orders = sum(1 for parts in self.p.orders.values() if all(p in covered for p in parts))
        satisfied = []
        for lock in self.locks:
            got = assignments.get(lock.part_id)
            if lock.lock_kind == "none" or got is None or got.remnant_id != lock.remnant_id:
                continue
            if lock.lock_kind == "placement" and (got.x_mm, got.y_mm, got.rot) != (lock.x_mm, lock.y_mm, lock.rot)                     and not self.s.is_tempered(self.s.parts[lock.part_id].material_id):
                continue
            satisfied.append(lock.part_id)
        return SolveOutcome(
            assignments={pid: (Assignment(a.part_id, a.remnant_id, a.x_mm, a.y_mm, a.rot,
                                          next(lk.lock_kind for lk in self.locks if lk.part_id == pid))
                               if pid in satisfied else a) for pid, a in assignments.items()},
            locks_satisfied=len(satisfied),
            covered_area=area,
            full_orders=full_orders,
            free_original=free_original,
            meets_min_free=free_original >= min(self.settings.minimum_free_remnants, len(self.p.original_available)),
            stage=stage,
        )

    def _secondary(self, outcome: SolveOutcome) -> tuple:
        stable = sum(
            1
            for pid, a in outcome.assignments.items()
            if (prev := self.p.previous.get(pid)) is not None
            and (prev.remnant_id, prev.x_mm, prev.y_mm, prev.rot) == (a.remnant_id, a.x_mm, a.y_mm, a.rot)
        )
        used = {a.remnant_id for a in outcome.assignments.values()}
        age = sum(self.s.remnants[r].age_days or 0 for r in used)
        return (stable, age)

    def key(self, outcome: SolveOutcome) -> tuple:
        # Lexicographic: user locks, five free originals, covered area, fully covered orders, stability, age.
        return (outcome.locks_satisfied, outcome.meets_min_free, outcome.covered_area, outcome.full_orders,
                *self._secondary(outcome))

    def offer(self, assignments: dict[str, Assignment], stage: str) -> bool:
        outcome = self.evaluate(assignments, stage)
        if outcome is None:
            return False
        if self.best_unconstrained is None or (
            outcome.covered_area, outcome.full_orders
        ) > (self.best_unconstrained.covered_area, self.best_unconstrained.full_orders):
            self.best_unconstrained = outcome
        if self.best is None or self.key(outcome) > self.key(self.best):
            self.best = outcome
            outcome.elapsed_seconds = round(self.elapsed(), 3)
            self.stats["incumbents"] += 1
            self.cb.incumbent(self._finish(outcome, interim=True))
            return True
        return False

    # -- stage 1: tempered + greedy ----------------------------------------------------------
    def tempered_patterns(self) -> list[Pattern]:
        patterns = []
        for pid in self.p.tempered_parts:
            part = self.s.parts[pid]
            for rid in self.p.elig.eligible[pid]:
                remnant = self.s.remnants[rid]
                rot = 0 if (abs(part.length_mm - remnant.length_mm) <= 2 and abs(part.width_mm - remnant.width_mm) <= 2) else 1
                patterns.append(Pattern(rid, ((pid, 0, 0, rot),), part.area))
        return patterns

    def tempered_matching(self) -> dict[str, Assignment]:
        """Exact maximum-weight bipartite matching by covered area (Hungarian algorithm)."""
        from scipy.optimize import linear_sum_assignment

        parts = [p for p in self.p.tempered_parts if self.p.elig.eligible[p]]
        remnants = sorted({r for p in parts for r in self.p.elig.eligible[p]})
        if not parts:
            return {}
        index = {r: j for j, r in enumerate(remnants)}
        weight = np.zeros((len(parts), len(remnants)))
        for i, pid in enumerate(parts):
            for rid in self.p.elig.eligible[pid]:
                weight[i, index[rid]] = self.s.parts[pid].area
        rows, cols = linear_sum_assignment(weight, maximize=True)
        result = {}
        by_part = {p.part_ids[0] + "|" + p.remnant_id: p for p in self.tempered_patterns()}
        for i, j in zip(rows, cols, strict=True):
            if weight[i, j] > 0:
                pattern = by_part[parts[i] + "|" + remnants[j]]
                pid, x, y, rot = pattern.placements[0]
                result[pid] = Assignment(pid, remnants[j], x, y, rot)
        # A locked tempered part must stay on its remnant: Hungarian on the restricted graph ensures it
        # when feasible; otherwise report it.
        for pid, rid in self.p.lock_remnant.items():
            if pid in self.p.tempered_parts and (pid not in result or result[pid].remnant_id != rid):
                self.p.conflicts.append(Issue("LOCK_CONFLICT", "Калёная деталь не может остаться на закрепленном куске.",
                                              pid, rid))
        return result

    def greedy_global(self, run: int, kind: str, heuristic: str, split: str, policy: str) -> dict[str, Assignment]:
        keys: list[str] = []
        bins = {}
        for rid in self.p.available:
            if self.s.is_tempered(self.s.remnants[rid].material_id):
                continue
            if rid in self.p.by_remnant or rid in self.p.fixed_place:
                bins[rid] = self.p.new_bin(rid, kind, heuristic, split, keys)
        locked_first = [p for p in self.p.ordinary_parts if p in self.p.lock_remnant and
                        p not in self.p.fixed_place.get(self.p.lock_remnant[p], {})]
        rest = [p for p in self.p.ordinary_parts if p not in self.p.lock_remnant and self.p.elig.eligible[p]]
        order = locked_first + _ordered(rest, self.s, self.rng, run)
        for pid in order:
            part = self.s.parts[pid]
            item = Item(len(keys), part.length_mm, part.width_mm)
            best = None
            for rid in self.p.elig.eligible[pid]:
                bin_ = bins.get(rid)
                if bin_ is None:
                    continue
                choice = bin_.best(item)
                if choice is None:
                    continue
                if policy == "used_first":
                    score = (0 if bin_.placed else 1, choice[0])
                elif policy == "small_first":
                    score = (self.s.remnants[rid].area, choice[0])
                elif policy == "old_first":
                    score = (-(self.s.remnants[rid].age_days or 0), choice[0])
                else:
                    score = (choice[0],)
                if best is None or score < best[0]:
                    best = (score, rid, choice)
            if best is None:
                continue
            keys.append(pid)
            bins[best[1]].apply(item.key, best[2])
        result: dict[str, Assignment] = {}
        for rid, bin_ in bins.items():
            pattern = self.p.pattern_from_bin(rid, bin_.placed, keys)
            if not pattern.placements:
                continue
            if not self.p.pattern_ok_for_locks(pattern):
                continue
            self.pool.add(pattern)
            for pid, x, y, rot in pattern.placements:
                result[pid] = Assignment(pid, rid, x, y, rot)
        return result

    def greedy_config(self, run: int) -> tuple[str, str, str, str]:
        kind = "maxrects" if run % 2 else "guillotine"
        heuristic = HEURISTICS[(run // 2) % len(HEURISTICS)]
        split = SPLITS[(run // 8) % len(SPLITS)]
        policy = ("global", "used_first", "small_first", "old_first")[(run // 3) % 4]
        return kind, heuristic, split, policy

    def first_plan(self, tempered: dict[str, Assignment]) -> None:
        self.cb.progress("first_plan", 0, None)
        runs = self.profile["greedy"]
        deadline = self.settings.first_plan_seconds
        done = 0
        for run in range(runs):
            if done and self.should_stop():
                break
            assignments = dict(tempered)
            assignments.update(self.greedy_global(run, *self.greedy_config(run)))
            self.offer(assignments, "greedy")
            done += 1
            if self.settings.profile == "quick" and not self.settings.fixed_work and self.elapsed() > deadline:
                self.stop_reason = "time_limit"
                break
        self.stats["greedy_runs"] = done

    # -- stage 2: pool ------------------------------------------------------------------------
    def fill(self, rid: str, order: list[str], kind: str, heuristic: str, split: str) -> Pattern | None:
        keys: list[str] = []
        bin_ = self.p.new_bin(rid, kind, heuristic, split, keys)
        required = [p for p in self.p.required.get(rid, ()) if p not in self.p.fixed_place.get(rid, {})]
        for pid in required + [p for p in order if p not in self.p.required.get(rid, ())]:
            part = self.s.parts[pid]
            keys.append(pid)
            if not bin_.insert(Item(len(keys) - 1, part.length_mm, part.width_mm)):
                keys.pop()
        pattern = self.p.pattern_from_bin(rid, bin_.placed, keys)
        if not pattern.placements or not self.p.pattern_ok_for_locks(pattern):
            return None
        return pattern

    def random_fills(self) -> None:
        count = self.profile["fills"]
        remnants = [r for r in self.p.available if r in self.p.by_remnant and not self.s.is_tempered(
            self.s.remnants[r].material_id)]
        for i in range(count):
            if self.should_stop(reserve=self.settings.time_limit_seconds * 0.5):
                return
            for rid in remnants:
                order = _ordered(self.p.by_remnant[rid], self.s, self.rng, i + 1)
                kind = "maxrects" if (i + len(rid)) % 3 else "guillotine"
                heuristic = HEURISTICS[i % len(HEURISTICS)]
                pattern = self.fill(rid, order, kind, heuristic, SPLITS[i % len(SPLITS)])
                if pattern:
                    self.pool.add(pattern)
                    # Sub-patterns without one part give the MILP more freedom at no geometric cost.
                    if len(pattern.placements) > 1 and i % 4 == 0:
                        for drop in range(len(pattern.placements)):
                            rest = pattern.placements[:drop] + pattern.placements[drop + 1:]
                            sub = Pattern(rid, rest, sum(self.s.parts[p[0]].area for p in rest))
                            if self.p.pattern_ok_for_locks(sub):
                                self.pool.add(sub)
            self.cb.progress("pattern_pool", i + 1, count)
        self.stats["pool_after_fills"] = len(self.pool)

    # -- MILP ---------------------------------------------------------------------------------
    def _matrix(self, patterns: list[Pattern]):
        from scipy.sparse import csr_matrix

        part_rows = {pid: i for i, pid in enumerate(self.s.part_order)}
        remnant_rows = {rid: len(part_rows) + j for j, rid in enumerate(self.p.available)}
        n_rows = len(part_rows) + len(remnant_rows)
        data, rows, cols = [], [], []
        for k, pattern in enumerate(patterns):
            for pid in pattern.part_ids:
                rows.append(part_rows[pid])
                cols.append(k)
                data.append(1.0)
            rows.append(remnant_rows[pattern.remnant_id])
            cols.append(k)
            data.append(1.0)
        matrix = csr_matrix((data, (rows, cols)), shape=(n_rows, len(patterns)))
        return matrix, part_rows, remnant_rows

    def _constraints(self, patterns: list[Pattern], with_free: bool):
        from scipy.optimize import LinearConstraint
        from scipy.sparse import csr_matrix

        matrix, part_rows, remnant_rows = self._matrix(patterns)
        lower = np.full(matrix.shape[0], -np.inf)
        upper = np.ones(matrix.shape[0])
        for pid in self.p.lock_remnant:
            if pid in part_rows and any(pid in p.part_ids for p in patterns):
                lower[part_rows[pid]] = 1.0
        for rid in self.p.required:
            if rid in remnant_rows and any(p.remnant_id == rid for p in patterns):
                lower[remnant_rows[rid]] = 1.0
        constraints = [LinearConstraint(matrix, lower, upper)]
        free_row = None
        need = min(self.settings.minimum_free_remnants, len(self.p.original_available))
        if with_free and need > 0:
            originals = {r for r in self.p.original_available}
            row = np.array([1.0 if p.remnant_id in originals else 0.0 for p in patterns])
            constraints.append(LinearConstraint(csr_matrix(row.reshape(1, -1)), -np.inf, len(originals) - need))
            free_row = True
        return constraints, free_row

    def milp_select(self, with_free: bool = True, secondary_floor: int | None = None) -> tuple[list[Pattern], dict]:
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import csr_matrix

        patterns = [p for p in self.pool.patterns if self.p.pattern_ok_for_locks(p)]
        if not patterns:
            return [], {"status": "empty"}
        constraints, _ = self._constraints(patterns, with_free)
        area = np.array([float(p.area) for p in patterns])
        n = len(patterns)
        time_left = max(1.0, self.settings.time_limit_seconds - self.elapsed())
        options = {"time_limit": min(time_left, 120.0 if self.settings.fixed_work else 60.0), "mip_rel_gap": 0.0,
                   "presolve": True}
        if self.settings.fixed_work:
            # Deterministic work cap instead of relying on the wall clock (status 1 is reported if reached).
            options["node_limit"] = 100_000
        if secondary_floor is None:
            result = milp(-area, integrality=np.ones(n), bounds=Bounds(0, 1), constraints=constraints, options=options)
        else:
            # Phase 2: keep area >= floor, maximise fully covered orders, then stability, then age.
            orders = [o for o, parts in self.p.orders.items()
                      if all(any(pid in p.part_ids for p in patterns) for pid in parts)]
            n_orders = len(orders)
            total_parts = max(1, len(self.s.part_order))
            stability = np.zeros(n)
            age = np.zeros(n)
            denom_age = (self.p.max_age + 1) * (len(self.p.available) + 1)
            for k, pattern in enumerate(patterns):
                for pid, x, y, rot in pattern.placements:
                    prev = self.p.previous.get(pid)
                    if prev and (prev.remnant_id, prev.x_mm, prev.y_mm, prev.rot) == (pattern.remnant_id, x, y, rot):
                        stability[k] += 1
                age[k] = (self.s.remnants[pattern.remnant_id].age_days or 0) / denom_age
            c = np.concatenate([-(stability + age) / (total_parts + 1), -np.ones(n_orders)])
            # Extend existing constraints with zero columns for order variables.
            extended = []
            for con in constraints:
                a = csr_matrix(con.A)
                extended.append(LinearConstraint(
                    csr_matrix((a.data, a.indices, a.indptr), shape=(a.shape[0], n + n_orders)), con.lb, con.ub))
            extended.append(LinearConstraint(
                csr_matrix(np.concatenate([area, np.zeros(n_orders)]).reshape(1, -1)), secondary_floor - 0.5, np.inf))
            if n_orders:
                rows, cols, data = [], [], []
                row = 0
                index = {}
                for k, pattern in enumerate(patterns):
                    for pid in pattern.part_ids:
                        index.setdefault(pid, []).append(k)
                for j, order_id in enumerate(orders):
                    for pid in self.p.orders[order_id]:
                        rows.append(row)
                        cols.append(n + j)
                        data.append(1.0)
                        for k in index.get(pid, []):
                            rows.append(row)
                            cols.append(k)
                            data.append(-1.0)
                        row += 1
                extended.append(LinearConstraint(
                    csr_matrix((data, (rows, cols)), shape=(row, n + n_orders)), -np.inf, 0.0))
            result = milp(c, integrality=np.ones(n + n_orders), bounds=Bounds(0, 1), constraints=extended,
                          options={**options, "mip_rel_gap": 1e-9})
        if result.x is None:
            return [], {"status": int(result.status), "message": str(result.message)}
        chosen = [patterns[k] for k in range(n) if result.x[k] > 0.5]
        info = {"status": int(result.status), "patterns": n,
                "gap": None if getattr(result, "mip_gap", None) is None else float(result.mip_gap)}
        return chosen, info

    def to_assignments(self, chosen: list[Pattern]) -> dict[str, Assignment]:
        result = {}
        for pattern in chosen:
            for pid, x, y, rot in pattern.placements:
                result[pid] = Assignment(pid, pattern.remnant_id, x, y, rot)
        return result

    # -- column generation --------------------------------------------------------------------
    def lp_duals(self) -> tuple[dict[str, float], dict[str, float], float] | None:
        from scipy.optimize import linprog

        patterns = [p for p in self.pool.patterns if self.p.pattern_ok_for_locks(p)]
        if not patterns:
            return None
        matrix, part_rows, remnant_rows = self._matrix(patterns)
        need = min(self.settings.minimum_free_remnants, len(self.p.original_available))
        originals = set(self.p.original_available)
        a_ub = matrix
        b_ub = np.ones(matrix.shape[0])
        if need > 0:
            from scipy.sparse import csr_matrix, vstack

            row = csr_matrix(np.array([1.0 if p.remnant_id in originals else 0.0 for p in patterns]).reshape(1, -1))
            a_ub = vstack([matrix, row]).tocsr()
            b_ub = np.concatenate([b_ub, [len(originals) - need]])
        area = np.array([float(p.area) for p in patterns])
        res = linprog(-area, A_ub=a_ub, b_ub=b_ub, bounds=(0, None), method="highs")
        if res.status != 0:
            return None
        marg = -np.asarray(res.ineqlin.marginals)
        pi = {pid: float(marg[i]) for pid, i in part_rows.items()}
        mu = {rid: float(marg[i]) for rid, i in remnant_rows.items()}
        lam = float(marg[-1]) if need > 0 else 0.0
        self.stats["lp_bound_pool_mm2"] = float(-res.fun)
        return pi, mu, lam

    def price_heuristic(self, duals, rounds: int) -> int:
        pi, mu, lam = duals
        added = 0
        originals = set(self.p.original_available)
        for rid in self.p.available:
            if rid not in self.p.by_remnant or self.s.is_tempered(self.s.remnants[rid].material_id):
                continue
            values = {p: self.s.parts[p].area - pi.get(p, 0.0) for p in self.p.by_remnant[rid]}
            candidates = [p for p, v in values.items() if v > 1e-6 or p in self.p.required.get(rid, ())]
            if not candidates:
                continue
            threshold = mu.get(rid, 0.0) + (lam if rid in originals else 0.0)
            for attempt in range(rounds):
                if attempt == 0:
                    order = sorted(candidates, key=lambda p: (-values[p], p))
                elif attempt == 1:
                    order = sorted(candidates, key=lambda p: (-values[p] / self.s.parts[p].area, -values[p], p))
                else:
                    order = sorted(candidates, key=lambda p: -values[p] * self.rng.uniform(0.5, 1.6))
                kind = "maxrects" if attempt % 3 != 2 else "guillotine"
                pattern = self.fill(rid, order, kind, HEURISTICS[attempt % len(HEURISTICS)], SPLITS[attempt % 4])
                if pattern is None:
                    continue
                reduced = sum(values[p] for p in pattern.part_ids) - threshold
                if reduced > 1e-3 and self.pool.add(pattern):
                    added += 1
        return added

    def cpsat_pack(self, remnant_ids: list[str], candidates: list[str], values: dict[str, int],
                   seconds: float) -> list[Pattern]:
        """Exact (within time) multi-remnant packing with official axis geometry via NoOverlap2D."""
        from ortools.sat.python import cp_model

        model = cp_model.CpModel()
        presence: dict[tuple[str, str, int], cp_model.IntVar] = {}
        coords: dict[tuple[str, str, int], tuple] = {}
        per_part: dict[str, list] = defaultdict(list)
        for rid in remnant_ids:
            remnant = self.s.remnants[rid]
            cx, cy, cw, ch = TRIM_MM, TRIM_MM, remnant.length_mm - 2 * TRIM_MM + GAP_MM, remnant.width_mm - 2 * TRIM_MM + GAP_MM
            xs, ys = [], []
            fixed = self.p.fixed_place.get(rid, {})
            for pid in candidates:
                if rid not in self.p.elig.eligible.get(pid, []):
                    continue
                part = self.s.parts[pid]
                for rot in (0, 1):
                    w, h = oriented_size(part, rot)
                    w += GAP_MM
                    h += GAP_MM
                    if w > cw or h > ch:
                        continue
                    if pid in fixed and fixed[pid][2] != rot:
                        continue
                    b = model.NewBoolVar(f"b_{pid}_{rid}_{rot}")
                    if pid in fixed:
                        x = model.NewConstant(fixed[pid][0])
                        y = model.NewConstant(fixed[pid][1])
                        model.Add(b == 1)
                    else:
                        x = model.NewIntVar(cx, cx + cw - w, f"x_{pid}_{rid}_{rot}")
                        y = model.NewIntVar(cy, cy + ch - h, f"y_{pid}_{rid}_{rot}")
                    xs.append(model.NewOptionalFixedSizeIntervalVar(x, w, b, f"ix_{pid}_{rid}_{rot}"))
                    ys.append(model.NewOptionalFixedSizeIntervalVar(y, h, b, f"iy_{pid}_{rid}_{rot}"))
                    presence[(pid, rid, rot)] = b
                    coords[(pid, rid, rot)] = (x, y)
                    per_part[pid].append(b)
            if xs:
                model.AddNoOverlap2D(xs, ys)
            for pid in self.p.required.get(rid, ()):
                model.Add(sum(presence[k] for k in presence if k[0] == pid and k[1] == rid) == 1)
        for pid, bs in per_part.items():
            model.AddAtMostOne(bs)
        if not presence:
            return []
        model.Maximize(sum(values.get(k[0], 0) * b for k, b in presence.items()))
        solver = cp_model.CpSolver()
        if self.settings.fixed_work:
            solver.parameters.max_deterministic_time = seconds
            solver.parameters.num_workers = 1
        else:
            solver.parameters.max_time_in_seconds = seconds
            solver.parameters.num_workers = max(1, self.settings.workers)
        solver.parameters.random_seed = self.settings.seed
        status = solver.Solve(model)
        self.stats["cpsat_calls"] += 1
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return []
        if status == cp_model.OPTIMAL:
            self.stats["cpsat_optimal"] += 1
        by_rid: dict[str, list] = defaultdict(list)
        for (pid, rid, rot), b in presence.items():
            if solver.Value(b):
                x, y = coords[(pid, rid, rot)]
                by_rid[rid].append((pid, int(solver.Value(x)), int(solver.Value(y)), rot))
        patterns = []
        for rid, placements in by_rid.items():
            placements.sort()
            patterns.append(Pattern(rid, tuple(placements), sum(self.s.parts[p[0]].area for p in placements)))
        return patterns

    def price_cpsat(self, duals, budget_remnants: int, seconds: float) -> int:
        pi, mu, lam = duals
        originals = set(self.p.original_available)
        added = 0
        remnants = [r for r in self.p.available if r in self.p.by_remnant and not self.s.is_tempered(
            self.s.remnants[r].material_id)]
        self.rng.shuffle(remnants)
        for rid in remnants[:budget_remnants]:
            if self.should_stop(reserve=5):
                break
            values = {p: self.s.parts[p].area - pi.get(p, 0.0) for p in self.p.by_remnant[rid]}
            candidates = [p for p, v in values.items() if v > 1e-6 or p in self.p.required.get(rid, ())]
            if not candidates:
                continue
            ints = {p: max(0, int(round(values[p]))) for p in candidates}
            for pattern in self.cpsat_pack([rid], candidates, ints, seconds):
                reduced = sum(values[p] for p in pattern.part_ids) - mu.get(rid, 0.0) - (
                    lam if rid in originals else 0.0)
                if self.p.pattern_ok_for_locks(pattern) and reduced > 1e-3 and self.pool.add(pattern):
                    added += 1
        return added

    def lns(self, seconds: float) -> int:
        """Destroy a few remnants of one material in the incumbent and repair them exactly with CP-SAT."""
        if self.best is None:
            return 0
        current = self.best.assignments
        by_rid: dict[str, list[str]] = defaultdict(list)
        for pid, a in current.items():
            by_rid[a.remnant_id].append(pid)
        materials = [m for m in self.p.materials if not self.s.is_tempered(m)]
        if not materials:
            return 0
        material = self.rng.choice(materials)
        remnants = [r for r in self.p.available if self.s.remnants[r].material_id == material and r in self.p.by_remnant]
        if not remnants:
            return 0
        used = [r for r in remnants if r in by_rid]
        free = [r for r in remnants if r not in by_rid]
        k = self.rng.randint(2, 4)
        chosen = self.rng.sample(used, min(k, len(used)))
        if free and self.rng.random() < 0.5:
            chosen.append(self.rng.choice(free))
        if not chosen:
            return 0
        own = [p for r in chosen for p in by_rid.get(r, [])]
        uncovered = [p for p in self.p.ordinary_parts if p not in current and
                     any(r in chosen for r in self.p.elig.eligible[p])]
        uncovered.sort(key=lambda p: -self.s.parts[p].area * self.rng.uniform(0.6, 1.4))
        candidates = own + uncovered[: max(8, 40 - len(own))]
        values = {p: self.s.parts[p].area for p in candidates}
        added = 0
        for pattern in self.cpsat_pack(chosen, candidates, values, seconds):
            if self.p.pattern_ok_for_locks(pattern) and self.pool.add(pattern):
                added += 1
        self.stats["lns_moves"] += 1
        return added

    def _pricing_budget(self) -> float:
        if self.settings.pricing_seconds is not None:
            return self.settings.pricing_seconds
        return 1.0 if self.settings.profile == "extended" else 0.5

    def _lns_budget(self) -> float:
        if self.settings.lns_seconds is not None:
            return self.settings.lns_seconds
        return 2.0 if self.settings.profile == "extended" else 1.0

    # -- main ---------------------------------------------------------------------------------
    def run(self) -> SolveOutcome:
        self.started = self.clock()
        tempered = self.tempered_matching()
        for pattern in self.tempered_patterns():
            if self.p.pattern_ok_for_locks(pattern):
                self.pool.add(pattern)
        self.first_plan(tempered)
        if self.best is None:
            # Nothing coverable or every candidate rejected: an all-NEW plan is still a valid complete plan.
            self.offer({}, "empty")
        milp_status = None
        if self.settings.profile != "quick" and not self.should_stop():
            self.random_fills()
            stagnant = 0
            rounds = self.profile["rounds"]
            for round_ in range(rounds):
                if self.should_stop(reserve=2.0):
                    break
                chosen, info = self.milp_select()
                milp_status = info.get("status")
                improved = self.offer(self.to_assignments(chosen), "milp") if chosen else False
                self.stats["milp_rounds"] = round_ + 1
                self.cb.progress("column_generation", round_ + 1, rounds)
                duals = self.lp_duals()
                added = 0
                if duals is not None and not self.should_stop(reserve=2.0):
                    added += self.price_heuristic(duals, 6)
                    if self.profile["cpsat"] and (added == 0 or round_ % 3 == 0) and not self.should_stop(reserve=5):
                        added += self.price_cpsat(duals, 6, self._pricing_budget())
                if self.profile["lns"] and round_ < self.profile["lns"]:
                    for _ in range(3):
                        if self.should_stop(reserve=5):
                            break
                        added += self.lns(self._lns_budget())
                self.stats["columns_added"] += added
                stagnant = 0 if (improved or added) else stagnant + 1
                if stagnant >= self.profile["patience"] or self.pool.full:
                    break
            if not self.should_stop(reserve=1.0):
                chosen, info = self.milp_select()
                milp_status = info.get("status")
                if chosen:
                    self.offer(self.to_assignments(chosen), "milp_final")
            # Secondary lexicographic objective on the final pool (never loses area: checked exactly).
            if self.best is not None and not self.should_stop(reserve=1.0):
                floor = self.best.covered_area
                chosen, info = self.milp_select(secondary_floor=floor)
                if chosen:
                    candidate = self.evaluate(self.to_assignments(chosen), "lexicographic")
                    if candidate and candidate.meets_min_free == self.best.meets_min_free and \
                            candidate.covered_area >= floor and self.key(candidate) > self.key(self.best):
                        self.best = candidate
                        self.cb.incumbent(self._finish(candidate, interim=True))
            # Best plan without the five-free constraint, for the explicit comparison (TZ section 11).
            if not self.should_stop(reserve=1.0):
                chosen, _ = self.milp_select(with_free=False)
                if chosen:
                    self.offer(self.to_assignments(chosen), "milp_unconstrained")
        outcome = self.best
        assert outcome is not None
        status = "feasible"
        if self.settings.profile != "quick" and milp_status == 0 and self.stop_reason == "completed":
            status = "optimal_in_pool"
        if self.stop_reason in {"time_limit", "cancelled"}:
            status = "limited"
        eligible_area = sum(self.s.parts[p].area for p in self.s.part_order if self.p.elig.eligible[p])
        if outcome.covered_area == eligible_area and outcome.meets_min_free:
            status = "proven_optimal"  # trivial certificate: every individually eligible part is covered
        outcome.search_status = status
        outcome.stop_reason = self.stop_reason
        return self._finish(outcome, interim=False)

    def _finish(self, outcome: SolveOutcome, interim: bool) -> SolveOutcome:
        new_reasons = {}
        for pid in self.s.part_order:
            if pid in outcome.assignments:
                continue
            reason = self.p.elig.reasons.get(pid)
            if reason is None:
                locked = self.p.lock_remnant.get(pid)
                reason = "LOCK_CONFLICT" if locked else "LIMITED_SEARCH"
            new_reasons[pid] = reason
        outcome.new_reasons = new_reasons
        conflicts = list(self.p.conflicts)
        reported = {c.part_id for c in conflicts}
        for lock in self.locks:
            got = outcome.assignments.get(lock.part_id)
            if lock.lock_kind != "none" and lock.part_id not in reported and (got is None or got.lock_kind == "none"):
                conflicts.append(Issue("LOCK_CONFLICT", f"Закрепление {lock.part_id} → {lock.remnant_id} не удалось "
                                       "выполнить совместно с другими закреплениями.", lock.part_id, lock.remnant_id))
        outcome.conflicts = conflicts
        stats = dict(self.stats)
        stats.update(
            pool_patterns=len(self.pool),
            pool_full=self.pool.full,
            elapsed_seconds=round(self.elapsed(), 3),
            profile=self.settings.profile,
            seed=self.settings.seed,
            workers=self.settings.workers,
            fixed_work=self.settings.fixed_work,
            time_limit_seconds=self.settings.time_limit_seconds,
            minimum_free_remnants=self.settings.minimum_free_remnants,
            interim=interim,
        )
        if self.best_unconstrained is not None:
            stats["unconstrained_best_area_mm2"] = self.best_unconstrained.covered_area
            stats["unconstrained_best_free_original"] = self.best_unconstrained.free_original
            stats["five_free_area_loss_mm2"] = max(0, self.best_unconstrained.covered_area - outcome.covered_area)
        outcome.stats = stats
        outcome.elapsed_seconds = round(self.elapsed(), 3)
        return outcome


def solve(snapshot: Snapshot, settings: SolverSettings | None = None, **kwargs) -> SolveOutcome:
    return CuttingSolver(snapshot, settings, **kwargs).run()


def score(coverage: float, invalid: int) -> float:
    """Contest cutting score (TZ section 11): coverage is a 0..1 share."""
    base = max(0.0, min(20.0, max(0.0, 20.0 * (coverage - 0.50) / 0.15)))
    return max(0.0, base - min(6.0, 0.3 * invalid))


__all__ = ["CuttingSolver", "Pattern", "SolveOutcome", "SolverSettings", "solve", "score"]
