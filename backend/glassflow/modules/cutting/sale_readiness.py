"""Bounded joint cutting/sale readiness with a preserved, independently checked baseline.

Only a trusted sales caller may supply eligibility. This is deliberately not an HTTP
operation accepting a buyer-compatible ID list from a browser.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import defaultdict

from glassflow.contracts.cutting import CutPlan, SaleReadiness, SolveInput, SolverConfig

from .conversion import snapshot_from_input, to_assignment, to_placement
from .domain import NEW, Assignment, tempered_orientation
from .engine import CuttingEngine, input_hash
from .geometry import validate_plan
from .metrics import compute_metrics
from .packing import Item, MaxRectsBin
from .solver import CuttingSolver, Pattern, SolverSettings


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def inventory_fingerprint(data: SolveInput) -> str:
    return _hash({'pieces': sorted((r.model_dump(mode='json') for r in data.remnants), key=lambda r: r['remnant_id']),
                  'unavailable': sorted(data.unavailable_remnant_ids), 'occupied': sorted(data.occupied_remnant_ids)})


def _direct_repair(full, task, baseline, eligible, minimum_free, unavailable, deadline, context):
    """Try complete per-piece relocations with the ordinary C2 packer, no native startup."""
    assignments = {p.part_id: to_assignment(p) for p in baseline.placements}
    locked = {p.part_id for p in task.locks if p.lock_kind != 'none'}
    used = {p.remnant_id for p in assignments.values() if p.remnant_id != NEW}
    for rid in sorted(used & eligible):
        if context is not None and context.cancelled():
            return None
        if time.perf_counter() >= deadline or len(eligible-used) >= minimum_free:
            break
        group = [p for p in assignments.values() if p.remnant_id == rid]
        if any(p.part_id in locked for p in group):
            continue
        material = full.parts[group[0].part_id].material_id
        for target in sorted(full.remnants):
            piece = full.remnants[target]
            if (target in used or target in eligible or target in unavailable or piece.status != 'available'
                    or piece.material_id != material or time.perf_counter() >= deadline):
                continue
            if piece.defect and any(full.parts[a.part_id].premium for a in group):
                continue
            replacements = []
            if full.is_tempered(material):
                if len(group) != 1:
                    continue
                rot = tempered_orientation(full.parts[group[0].part_id], piece)
                if rot is not None:
                    replacements = [Assignment(group[0].part_id, target, 0, 0, rot)]
            else:
                bin_ = MaxRectsBin(piece.length_mm, piece.width_mm, 'bssf')
                order = sorted(group, key=lambda a: (-full.parts[a.part_id].area, a.part_id))
                for i, a in enumerate(order):
                    part = full.parts[a.part_id]
                    if not bin_.insert(Item(i, part.length_mm, part.width_mm)):
                        break
                if len(bin_.placed) == len(group):
                    replacements = [Assignment(order[i].part_id, target, x, y, rot)
                                    for i, x, y, rot in bin_.placed]
            if len(replacements) != len(group):
                continue
            proposed = dict(assignments)
            proposed.update({a.part_id: a for a in replacements})
            report = validate_plan(full, proposed.values(), unavailable_remnant_ids=unavailable,
                                   locks=[to_assignment(p) for p in task.locks])
            if report.valid:
                assignments = proposed
                used.remove(rid)
                used.add(target)
                break
    if len(eligible-used) >= minimum_free:
        return list(assignments.values())
    return None


class _SaleSolver(CuttingSolver):
    def __init__(self, *args, sale_ids: set[str], minimum_sale_free: int, area_floor: int, **kwargs):
        self.sale_ids, self.minimum_sale_free, self.area_floor = sale_ids, minimum_sale_free, area_floor
        self.best_sale = None
        super().__init__(*args, **kwargs)

    def evaluate(self, assignments, stage):
        outcome = super().evaluate(assignments, stage)
        if outcome is None:
            return None
        used = {a.remnant_id for a in outcome.assignments.values() if a.remnant_id != NEW}
        sale_ready = len(self.sale_ids-used) >= self.minimum_sale_free
        if sale_ready and outcome.meets_min_free and outcome.locks_satisfied == len(self.p.lock_remnant):
            if self.best_sale is None or (outcome.covered_area, outcome.full_orders) > (
                    self.best_sale.covered_area, self.best_sale.full_orders):
                self.best_sale = outcome
        outcome.meets_min_free = outcome.meets_min_free and sale_ready and outcome.covered_area >= self.area_floor
        return outcome

    def _constraints(self, patterns, with_free):
        import numpy as np
        from scipy.optimize import LinearConstraint
        from scipy.sparse import csr_matrix

        constraints, free = super()._constraints(patterns, with_free)
        sale_row = np.array([int(p.remnant_id in self.sale_ids) for p in patterns], dtype=float)
        constraints.append(LinearConstraint(csr_matrix(sale_row.reshape(1, -1)), -np.inf,
                                            len(self.sale_ids)-self.minimum_sale_free))
        area = np.array([float(p.area) for p in patterns])
        constraints.append(LinearConstraint(csr_matrix(area.reshape(1, -1)), self.area_floor, np.inf))
        return constraints, free

    def bounded_master(self, max_seconds=None):
        import numpy as np
        from scipy.optimize import Bounds, milp

        patterns = [p for p in self.pool.patterns if self.p.pattern_ok_for_locks(p)]
        remaining = self.settings.time_limit_seconds-self.elapsed()
        if max_seconds is not None:
            remaining = min(remaining, max_seconds)
        if not patterns or remaining <= .005 or self.should_stop():
            return
        constraints, _ = self._constraints(patterns, True)
        result = milp(-np.array([float(p.area) for p in patterns]), integrality=np.ones(len(patterns)),
                      bounds=Bounds(0, 1), constraints=constraints,
                      options={'time_limit': max(.001, remaining), 'mip_rel_gap': 0.0, 'presolve': True})
        if result.x is not None:
            self.offer(self.to_assignments([p for i, p in enumerate(patterns) if result.x[i] > .5]), 'sale_master')


class _Callbacks:
    def __init__(self, context):
        self.context = context

    def cancelled(self):
        return self.context is not None and self.context.cancelled()

    def progress(self, stage, completed, total):
        if self.context is not None:
            self.context.progress('sale_readiness_' + stage, completed, total)

    def incumbent(self, outcome):
        # The caller receives only independently validated final alternatives below.
        return None


def ensure_sale_readiness(snapshot: SolveInput, baseline: CutPlan, eligible_original_ids: set[str],
                          registry_version: str, budget_seconds: float = 2, minimum_free: int = 5,
                          context=None) -> SaleReadiness:
    if not registry_version or not math.isfinite(budget_seconds) or not 0 < budget_seconds <= 30:
        raise ValueError('A registry version and a finite budget in (0,30] seconds are required')
    if minimum_free < 1:
        raise ValueError('minimum_free must be positive')
    started = time.perf_counter()
    unavailable = set(snapshot.unavailable_remnant_ids) | set(snapshot.occupied_remnant_ids)
    eligible = {r.remnant_id for r in snapshot.remnants if r.remnant_id in eligible_original_ids
                and r.original and r.status == 'available' and r.remnant_id not in unavailable}
    used = {p.remnant_id for p in baseline.placements if p.remnant_id != NEW}
    base_free = sorted(eligible-used)
    args = dict(dataset_id=snapshot.dataset_id, baseline=baseline, eligible_original_ids=sorted(eligible),
                baseline_free_eligible_ids=base_free, registry_version=registry_version,
                input_fingerprint=input_hash(snapshot), inventory_fingerprint=inventory_fingerprint(snapshot),
                registry_fingerprint=_hash({'version': registry_version, 'eligible_ids': sorted(eligible)}),
                minimum_free=minimum_free)
    engine = CuttingEngine()
    task = snapshot.model_copy(deep=True)
    locks = {p.part_id: p for p in baseline.requested_locks}
    locks.update({p.part_id: p for p in task.locks})
    task.locks = list(locks.values())
    full = engine._normalise(snapshot_from_input(task), set(task.unavailable_remnant_ids))
    report = validate_plan(full, [to_assignment(p) for p in baseline.placements],
        unavailable_remnant_ids=task.unavailable_remnant_ids, locks=[to_assignment(p) for p in task.locks])
    if baseline.dataset_id != task.dataset_id or baseline.status not in {'validated', 'committed'} or not report.valid:
        return SaleReadiness(**args, status='stale', reason_ru='Исходный план недопустим для текущих данных; требуется перепроверка.')
    actual_area = sum(full.parts[pid].area for pid in report.ok_part_ids)
    if actual_area != baseline.metrics.covered_area_mm2:
        return SaleReadiness(**args, status='stale', reason_ru='Метрики исходного плана не соответствуют текущим деталям.')
    if len(base_free) >= minimum_free:
        return SaleReadiness(**args, status='ready_unchanged', candidate_free_eligible_ids=base_free,
            delta_area_mm2=0, reason_ru='План уже оставляет достаточно исходных кусков с подтвержденными соответствиями; пересчет не нужен.')
    if len(eligible) < minimum_free:
        return SaleReadiness(**args, status='evidence_shortage',
            reason_ru='Во всем доступном складе недостаточно кусков с buyer evidence. Дополнительный поиск не создаст соответствия.')
    if context is not None and context.cancelled():
        return SaleReadiness(**args, status='cancelled', reason_ru='Отмена; исходный план сохранен.')
    repaired = _direct_repair(full, task, baseline, eligible, minimum_free, unavailable,
                              started+budget_seconds*.25, context)
    if context is not None and context.cancelled():
        return SaleReadiness(**args, status='cancelled', reason_ru='Отмена; исходный план сохранен.')
    if repaired is not None:
        checked = validate_plan(full, repaired, unavailable_remnant_ids=unavailable,
                                locks=[to_assignment(p) for p in task.locks])
        metrics, free_ids = compute_metrics(full, checked, baseline.metrics.new_reasons,
                                           excluded_remnant_ids=unavailable)
        candidate = CutPlan(dataset_id=task.dataset_id, plan_id='unsaved', revision=0, status='validated',
            placements=[to_placement(a) for a in repaired], metrics=metrics, free_original_remnant_ids=free_ids,
            search_status='feasible', stop_reason='bounded_sale_relocation_completed',
            config=task.config, requested_locks=task.locks, parent_plan_id=baseline.plan_id,
            parent_revision=baseline.revision, evidence={'engine': 'sale-ready-relocation/1',
                'registry_version': registry_version, 'input_sha256': input_hash(task)})
        return SaleReadiness(**args, status='ready_alternative', alternative=candidate,
            candidate_free_eligible_ids=sorted(eligible-{a.remnant_id for a in repaired}),
            delta_area_mm2=metrics.covered_area_mm2-actual_area, search_performed=True,
            elapsed_seconds=round(time.perf_counter()-started, 4),
            reason_ru='Полные группы деталей перенесены на свободные альтернативы без потери площади; исходный план сохранен.')
    settings = SolverSettings(profile='quick', seed=task.config.seed, time_limit_seconds=budget_seconds,
        workers=1, minimum_free_remnants=task.config.minimum_free_remnants,
        max_pool_patterns=min(task.config.max_pool_patterns, 20_000))
    solver = _SaleSolver(full, settings, unavailable=task.unavailable_remnant_ids,
        occupied=task.occupied_remnant_ids, locks=[to_assignment(p) for p in task.locks],
        previous={p.part_id: to_assignment(p) for p in baseline.placements}, callbacks=_Callbacks(context),
        sale_ids=eligible, minimum_sale_free=minimum_free, area_floor=actual_area)
    solver.started = started
    groups = defaultdict(list)
    for p in baseline.placements:
        if p.remnant_id != NEW:
            groups[p.remnant_id].append(p)
    for rid, placements in groups.items():
        solver.pool.add(Pattern(rid, tuple(sorted((p.part_id, p.x_mm or 0, p.y_mm or 0, p.rot or 0) for p in placements)),
                                sum(full.parts[p.part_id].area for p in placements)))
    if not solver.should_stop():
        tempered = solver.tempered_matching()
        for pattern in solver.tempered_patterns():
            solver.pool.add(pattern)
        # Include layouts on currently unused pieces; greedy incumbents alone may
        # never open the larger non-sale piece needed for an area-neutral switch.
        fill_deadline = started + budget_seconds * .35
        for rid in sorted(solver.p.available, key=lambda r: (r in eligible, full.remnants[r].area, r)):
            if time.perf_counter() >= fill_deadline or solver.should_stop():
                break
            if full.is_tempered(full.remnants[rid].material_id):
                continue
            order = sorted(solver.p.by_remnant[rid], key=lambda p: (-full.parts[p].area, p))
            pattern = solver.fill(rid, order, 'maxrects', 'bssf', 'sas')
            if pattern:
                solver.pool.add(pattern)
        for run in range(6):
            if solver.should_stop(reserve=budget_seconds*.45):
                break
            candidate = dict(tempered)
            candidate.update(solver.greedy_global(run, *solver.greedy_config(run)))
            solver.offer(candidate, 'sale_greedy')
    if not solver.should_stop():
        solver.bounded_master(max_seconds=max(.001, (budget_seconds-solver.elapsed())*.65))
    if (solver.best_sale is None or solver.best_sale.covered_area < actual_area) and not solver.should_stop():
        # A separately labelled trade-off, never a silent relaxation of the area floor.
        solver.area_floor = 0
        solver.bounded_master()
        solver.evaluate({}, 'sale_empty_tradeoff')
    elapsed = time.perf_counter()-started
    args.update(search_performed=True, elapsed_seconds=round(elapsed, 4))
    if context is not None and context.cancelled():
        return SaleReadiness(**args, status='cancelled', reason_ru='Отмена; исходный план сохранен.')
    outcome = solver.best_sale
    if outcome is None:
        return SaleReadiness(**args, status='limited', reason_ru='За ограниченный бюджет совместный вариант не найден; это не доказательство невозможности.')
    outcome = solver._finish(outcome, interim=False)
    outcome.meets_min_free = outcome.free_original >= settings.minimum_free_remnants
    outcome.search_status = 'limited' if elapsed >= budget_seconds else 'feasible'
    outcome.stop_reason = 'time_limit' if elapsed >= budget_seconds else 'bounded_sale_search_completed'
    config = SolverConfig(profile='quick', seed=task.config.seed, time_limit_seconds=max(1, math.ceil(budget_seconds)),
        workers=1, minimum_free_remnants=task.config.minimum_free_remnants)
    candidate = engine._plan(full, task, config, outcome, outcome.assignments, set(task.unavailable_remnant_ids),
        {'engine': 'sale-ready-pool/1', 'input_sha256': input_hash(task), 'registry_version': registry_version,
         'baseline_plan_id': baseline.plan_id, 'baseline_revision': baseline.revision}, started)
    free = sorted(eligible-{p.remnant_id for p in candidate.placements if p.remnant_id != NEW})
    if candidate.status != 'validated' or len(free) < minimum_free or not engine.validate(task, candidate).valid:
        return SaleReadiness(**args, status='limited', reason_ru='Кандидат не прошел независимую перепроверку; исходный план сохранен.')
    delta = candidate.metrics.covered_area_mm2-actual_area
    if delta >= 0:
        return SaleReadiness(**args, status='ready_alternative', alternative=candidate,
            candidate_free_eligible_ids=free, delta_area_mm2=delta,
            reason_ru='Найден отдельный проверенный вариант без потери площади; действующий план не заменен.')
    return SaleReadiness(**args, status='tradeoff_available', tradeoff=candidate,
        candidate_free_eligible_ids=free, delta_area_mm2=delta,
        reason_ru='Есть отдельный проверенный вариант с меньшей площадью. Это измеренная уступка, не доказательство ее необходимости; исходный план сохранен.')
