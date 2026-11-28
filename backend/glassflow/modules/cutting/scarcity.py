"""Bounded evidence about known uncovered orders, using exact joint feasibility.

No demand forecast, no order re-ranking, and no inference of whole-order capacity
from independent per-part fits. UNKNOWN from CP-SAT is never called impossible.
"""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict

from glassflow.contracts.cutting import Candidates, ScarcityExplanation, ScarcityRequest, ScarcityResult

from .conversion import to_placement
from .domain import GAP_MM, TRIM_MM, Assignment, PartSpec, Snapshot, ordinary_fits, tempered_orientation
from .eligibility import pair_reason
from .geometry import validate_plan


def _joint(snapshot: Snapshot, forced: dict[str, str], deadline: float):
    from ortools.sat.python import cp_model

    if time.perf_counter() >= deadline:
        return 'limited', []
    model = cp_model.CpModel()
    choices = defaultdict(list)
    rectangles = defaultdict(lambda: ([], []))
    tempered_choices = defaultdict(list)
    metadata = []
    for part in snapshot.parts.values():
        for rid, piece in snapshot.remnants.items():
            if rid in forced.values() and part.part_id in forced and forced[part.part_id] != rid:
                continue
            if part.part_id in forced and forced[part.part_id] != rid:
                continue
            if pair_reason(snapshot, part, piece) is not None:
                continue
            tempered = snapshot.is_tempered(part.material_id)
            rotations = [tempered_orientation(part, piece)] if tempered else ordinary_fits(part, piece)
            if part.length_mm == part.width_mm:
                rotations = rotations[:1]
            for rot in rotations:
                if rot is None:
                    continue
                present = model.new_bool_var(f'c{len(metadata)}')
                choices[part.part_id].append(present)
                if tempered:
                    x, y = 0, 0
                    tempered_choices[rid].append(present)
                else:
                    width, height = ((part.width_mm, part.length_mm) if rot else
                                     (part.length_mm, part.width_mm))
                    x = model.new_int_var(TRIM_MM, piece.length_mm-TRIM_MM-width, f'x{len(metadata)}')
                    y = model.new_int_var(TRIM_MM, piece.width_mm-TRIM_MM-height, f'y{len(metadata)}')
                    xi = model.new_optional_fixed_size_interval_var(x, width+GAP_MM, present, f'xi{len(metadata)}')
                    yi = model.new_optional_fixed_size_interval_var(y, height+GAP_MM, present, f'yi{len(metadata)}')
                    rectangles[rid][0].append(xi)
                    rectangles[rid][1].append(yi)
                metadata.append((part.part_id, rid, rot, x, y, present))
        if not choices[part.part_id]:
            return 'infeasible', []
        model.add_exactly_one(choices[part.part_id])
    for xs, ys in rectangles.values():
        model.add_no_overlap_2d(xs, ys)
    for group in tempered_choices.values():
        model.add_at_most_one(group)
    remaining = deadline-time.perf_counter()
    if remaining <= .001:
        return 'limited', []
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = remaining
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 42
    status = solver.solve(model)
    if status == cp_model.INFEASIBLE:
        return 'infeasible', []
    if status not in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        return 'limited', []
    assignments = [Assignment(pid, rid, solver.value(x) if not isinstance(x, int) else x,
                             solver.value(y) if not isinstance(y, int) else y, rot)
                   for pid, rid, rot, x, y, p in metadata if solver.boolean_value(p)]
    if not validate_plan(snapshot, assignments).valid:
        return 'limited', []
    return 'feasible', assignments


def analyze_scarcity(snapshot: Snapshot, request: ScarcityRequest, baseline: Candidates,
                     pending_part_ids: list[str], occupied: set[str], *, inventory_version: str,
                     plan_id: str | None = None, plan_revision: int | None = None) -> ScarcityResult:
    started = time.perf_counter()
    deadline = started+request.budget_ms/1000
    args = dict(dataset_id=snapshot.dataset_id, baseline=baseline, inventory_version=inventory_version,
                plan_id=plan_id, plan_revision=plan_revision)
    def result(status, **extra):
        return ScarcityResult(**args, status=status, elapsed_ms=round((time.perf_counter()-started)*1000, 3), **extra)
    if request.inventory_mode != 'free_whole_remnants' or baseline.covered_quantity != request.quantity:
        return result('not_applicable')
    if request.quantity > 6:
        return result('limited')
    free = {rid: r for rid, r in snapshot.remnants.items() if r.status == 'available' and rid not in occupied}
    request_part = PartSpec('__request__', '__request__', request.material_id,
                           request.dimensions.length_mm, request.dimensions.width_mm, request.premium)
    options = {rid for rid, r in free.items() if pair_reason(snapshot, request_part, r) is None}
    baseline_rows = baseline.candidates[:request.quantity]
    consumed = {c.remnant_id for c in baseline_rows}
    pending = [snapshot.parts[pid] for pid in pending_part_ids if pid in snapshot.parts]
    groups = defaultdict(list)
    for part in pending:
        groups[part.order_id].append(part)
    for order, parts in sorted(groups.items()):
        if time.perf_counter() >= deadline:
            return result('limited')
        candidates = {p.part_id: {rid for rid, r in free.items() if pair_reason(snapshot, p, r) is None}
                      for p in parts}
        scarce = {next(iter(ids)) for ids in candidates.values() if len(ids) == 1} & consumed
        if not scarce:
            continue
        relevant = options | set().union(*candidates.values())
        if len(parts)+request.quantity > 12 or len(relevant) > 16:
            continue
        prefix = '_request_' + hashlib.sha256(repr(request.model_dump()).encode()).hexdigest()[:10]
        while any(f'{prefix}_{i}' in snapshot.parts for i in range(request.quantity)):
            prefix += '_'
        request_ids = [f'{prefix}_{i}' for i in range(request.quantity)]
        joint_parts = {p.part_id: p for p in parts}
        joint_parts.update({pid: PartSpec(pid, prefix, request.material_id, request.dimensions.length_mm,
            request.dimensions.width_mm, request.premium) for pid in request_ids})
        joint = Snapshot(snapshot.dataset_id, snapshot.materials, {r: free[r] for r in relevant}, joint_parts)
        # Prove that the baseline piece assignments cannot cover this known order
        # jointly. Do not use independent fits or a timeout as that proof.
        before, _ = _joint(joint, {pid: row.remnant_id for pid, row in zip(request_ids, baseline_rows)}, deadline)
        if before == 'limited':
            return result('limited')
        if before != 'infeasible':
            continue
        for alternative in sorted(options-consumed):
            if time.perf_counter() >= deadline:
                return result('limited')
            after, witness = _joint(joint, dict.fromkeys(request_ids, alternative), deadline)
            if after == 'limited':
                return result('limited')
            if after != 'feasible':
                continue
            preserve = sorted(scarce)[0]
            explanation = ScarcityExplanation(preserve_remnant_id=preserve,
                alternative_remnant_id=alternative, known_order_id=order,
                pending_part_ids=sorted(p.part_id for p in parts), request_part_ids=request_ids,
                joint_witness=[to_placement(a) for a in witness],
                reason_ru=(f'Оставим {preserve} для известных нераспределенных деталей заказа {order}. '
                    f'Если заявка размещена на {alternative}, для нее и всех {len(parts)} деталей есть совместная допустимая раскладка; '
                    'с текущими назначениями заявки такая совместная раскладка невозможна. Это не прогноз спроса.'))
            return result('proved', recommended_remnant_id=alternative, explanations=[explanation])
    return result('limited' if time.perf_counter() >= deadline else 'no_proof')
