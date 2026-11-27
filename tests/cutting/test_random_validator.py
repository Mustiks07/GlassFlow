"""T13: random small problems — internal validity agrees with the unmodified validate.py.

Agreement rule: on complete plans with unique part IDs and integer coordinates (the domain where the
official script is defined), the set of parts the official script accepts equals the set our
validator accepts, and our plan is valid iff the official script reports zero errors.
Our validator is additionally stricter (missing parts, duplicates, strict format) — tested in T12.
"""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from glassflow.modules.cutting.domain import NEW, Assignment
from glassflow.modules.cutting.geometry import validate_plan
from glassflow.modules.cutting.solver import SolverSettings, solve

from .conftest import make_snapshot, official_module, official_rows

OFFICIAL = official_module()
MATERIALS = ["clear-4", "mirror-4", "temp-6"]


@st.composite
def problems(draw):
    n_rem = draw(st.integers(1, 4))
    n_parts = draw(st.integers(1, 6))
    remnants = []
    for i in range(n_rem):
        remnants.append((f"R{i}", draw(st.sampled_from(MATERIALS)), draw(st.integers(20, 160)),
                         draw(st.integers(20, 160)), draw(st.booleans())))
    parts = []
    for j in range(n_parts):
        parts.append((f"P{j}", f"O{j % 3}", draw(st.sampled_from(MATERIALS)), draw(st.integers(5, 120)),
                      draw(st.integers(5, 120)), draw(st.booleans())))
    snap = make_snapshot(remnants, parts)
    rows = []
    for pid, *_ in parts:
        if draw(st.booleans()):
            rows.append(Assignment(pid, NEW))
            continue
        rid = draw(st.sampled_from([r[0] for r in remnants]))
        rows.append(Assignment(pid, rid, draw(st.integers(0, 60)), draw(st.integers(0, 60)), draw(st.integers(0, 1))))
    return snap, rows


def official(snap, rows):
    stock, orders, mats = official_rows(snap)
    sol = [{"part_id": a.part_id, "remnant_id": a.remnant_id, "x_mm": "" if a.x_mm is None else str(a.x_mm),
            "y_mm": "" if a.y_mm is None else str(a.y_mm), "rot": "" if a.rot is None else str(a.rot)} for a in rows]
    _, _, ok, bad = OFFICIAL.check(stock, orders, sol, mats)
    return ok, bad


@settings(max_examples=600, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(problems())
def test_t13_random_plans_agree_with_official_validator(problem):
    snap, rows = problem
    # Tempered rows: the official script ignores coordinates; we accept empty or (0,0,matching rot) only.
    rows = [Assignment(a.part_id, a.remnant_id, None, None, None)
            if a.remnant_id in snap.remnants and snap.is_tempered(snap.remnants[a.remnant_id].material_id) else a
            for a in rows]
    report = validate_plan(snap, rows)
    ok, bad = official(snap, rows)
    assert report.valid == (not bad)
    if report.valid:
        assert report.ok_part_ids == ok
    else:
        # every part the official script flags is flagged by us as well
        assert {b[0] for b in bad} <= set(report.invalid_part_ids)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(problems())
def test_t13_solver_output_always_valid_complete_and_officially_clean(problem):
    snap, _ = problem
    outcome = solve(snap, SolverSettings(profile="quick", time_limit_seconds=5, minimum_free_remnants=0))
    rows = outcome.rows(snap)
    report = validate_plan(snap, rows)
    assert report.valid, [i.as_text() for i in report.issues]
    assert len(rows) == len(snap.parts)
    ok, bad = official(snap, rows)
    assert bad == [] and set(ok) == set(outcome.assignments)
