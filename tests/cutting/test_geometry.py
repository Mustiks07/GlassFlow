"""T08–T12 and validator error contract. Each case also runs the official validate.py check()."""

import pytest

from glassflow.modules.cutting.domain import NEW, Assignment
from glassflow.modules.cutting.geometry import parse_solution_rows, validate_plan

from .conftest import make_snapshot, official_module, official_rows

OFFICIAL = official_module()


def check_both(snapshot, rows):
    report = validate_plan(snapshot, rows)
    stock, orders, mats = official_rows(snapshot)
    sol = [{"part_id": a.part_id, "remnant_id": a.remnant_id, "x_mm": "" if a.x_mm is None else str(a.x_mm),
            "y_mm": "" if a.y_mm is None else str(a.y_mm), "rot": "" if a.rot is None else str(a.rot)} for a in rows]
    _, _, ok, bad = OFFICIAL.check(stock, orders, sol, mats)
    return report, ok, bad


def codes(report):
    return {i.code for i in report.issues}


# T08 -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("x,valid", [(5, True), (4, False)])
def test_t08_left_edge_exactly_5mm_and_1mm_beyond(x, valid):
    snap = make_snapshot([("R1", "clear-4", 300, 200, False)], [("P1", "O1", "clear-4", 100, 100, False)])
    report, ok, bad = check_both(snap, [Assignment("P1", "R1", x, 5, 0)])
    assert report.valid is valid and (not bad) is valid
    if not valid:
        issue = report.issues[0]
        assert issue.code == "OUT_OF_BOUNDS" and issue.part_id == "P1" and issue.coordinates["x_mm"] == 4


@pytest.mark.parametrize("right,valid", [(195, True), (196, False)])
def test_t08_right_and_bottom_edge(right, valid):
    # remnant 300x200: x+w <= 295 and y+h <= 195
    snap = make_snapshot([("R1", "clear-4", 300, 200, False)], [("P1", "O1", "clear-4", 100, 100, False)])
    report, _, bad = check_both(snap, [Assignment("P1", "R1", right, 95 if valid else 96, 0)])
    assert report.valid is valid and (not bad) is valid


# T09 -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("gap,valid", [(3, True), (2, False)])
def test_t09_gap_3mm_ok_2mm_rejected(gap, valid):
    snap = make_snapshot([("R1", "clear-4", 400, 200, False)],
                         [("P1", "O1", "clear-4", 100, 100, False), ("P2", "O1", "clear-4", 100, 100, False)])
    rows = [Assignment("P1", "R1", 5, 5, 0), Assignment("P2", "R1", 105 + gap, 5, 0)]
    report, _, bad = check_both(snap, rows)
    assert report.valid is valid and (not bad) is valid
    if not valid:
        assert codes(report) == {"GAP_VIOLATION"}
        assert {i.part_id for i in report.issues} == {"P1", "P2"}


def test_t09_diagonal_parts_separated_on_one_axis_are_valid():
    snap = make_snapshot([("R1", "clear-4", 400, 400, False)],
                         [("P1", "O1", "clear-4", 100, 100, False), ("P2", "O1", "clear-4", 100, 100, False)])
    report, _, bad = check_both(snap, [Assignment("P1", "R1", 5, 5, 0), Assignment("P2", "R1", 106, 108, 0)])
    assert report.valid and not bad


def test_t09_overlap_reported_as_overlap():
    snap = make_snapshot([("R1", "clear-4", 400, 400, False)],
                         [("P1", "O1", "clear-4", 100, 100, False), ("P2", "O1", "clear-4", 100, 100, False)])
    report, _, bad = check_both(snap, [Assignment("P1", "R1", 5, 5, 0), Assignment("P2", "R1", 50, 50, 0)])
    assert "OVERLAP" in codes(report) and bad


# T10 -----------------------------------------------------------------------------------------------
def test_t10_rotation_swaps_axes():
    snap = make_snapshot([("R1", "clear-4", 210, 310, False)], [("P1", "O1", "clear-4", 300, 200, False)])
    assert check_both(snap, [Assignment("P1", "R1", 5, 5, 1)])[0].valid
    report, _, bad = check_both(snap, [Assignment("P1", "R1", 5, 5, 0)])
    assert not report.valid and bad and codes(report) == {"OUT_OF_BOUNDS"}


def test_t10_material_mismatch_and_premium_on_defect_rejected():
    snap = make_snapshot([("R1", "clear-4", 500, 500, True), ("R2", "mirror-4", 500, 500, False)],
                         [("P1", "O1", "clear-4", 100, 100, True), ("P2", "O1", "clear-4", 100, 100, False),
                          ("P3", "O2", "mirror-4", 100, 100, False)])
    rows = [Assignment("P1", "R1", 5, 5, 0), Assignment("P2", "R2", 5, 5, 0), Assignment("P3", "R1", 300, 300, 0)]
    report, ok, bad = check_both(snap, rows)
    by_part = {i.part_id: i.code for i in report.issues}
    assert by_part == {"P1": "PREMIUM_ON_DEFECT", "P2": "MATERIAL_MISMATCH", "P3": "MATERIAL_MISMATCH"}
    assert {b[0] for b in bad} == {"P1", "P2", "P3"} and not ok


def test_t10_ordinary_part_on_defect_allowed():
    snap = make_snapshot([("R1", "clear-4", 500, 500, True)], [("P1", "O1", "clear-4", 100, 100, False)])
    assert check_both(snap, [Assignment("P1", "R1", 5, 5, 0)])[0].valid


# T11 -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("delta,valid", [(2, True), (-2, True), (3, False)])
def test_t11_tempered_tolerance(delta, valid):
    snap = make_snapshot([("T1", "temp-6", 600 + delta, 400, False)], [("P1", "O1", "temp-6", 600, 400, False)])
    report, ok, bad = check_both(snap, [Assignment("P1", "T1", 0, 0, 0)])
    assert report.valid is valid and (not bad) is valid
    if not valid:
        assert codes(report) == {"TEMPERED_SIZE_MISMATCH"}


def test_t11_tempered_rotated_match_and_no_trim():
    snap = make_snapshot([("T1", "temp-6", 400, 600, False)], [("P1", "O1", "temp-6", 601, 399, False)])
    assert check_both(snap, [Assignment("P1", "T1", 0, 0, 1)])[0].valid
    assert check_both(snap, [Assignment("P1", "T1", None, None, None)])[0].valid
    bad = validate_plan(snap, [Assignment("P1", "T1", 0, 0, 0)])  # wrong orientation for given rot
    assert codes(bad) == {"TEMPERED_BAD_COORDINATES"}


def test_t11_two_parts_on_tempered_rejected():
    snap = make_snapshot([("T1", "temp-6", 600, 400, False)],
                         [("P1", "O1", "temp-6", 600, 400, False), ("P2", "O1", "temp-6", 599, 401, False)])
    report, _, bad = check_both(snap, [Assignment("P1", "T1", 0, 0, 0), Assignment("P2", "T1", 0, 0, 0)])
    assert codes(report) == {"TEMPERED_MULTIPLE_PARTS"} and bad


# T12 -----------------------------------------------------------------------------------------------
def test_t12_duplicate_and_missing_parts_block_strict_plan():
    snap = make_snapshot([("R1", "clear-4", 500, 500, False)],
                         [("P1", "O1", "clear-4", 100, 100, False), ("P2", "O1", "clear-4", 100, 100, False)])
    dup = validate_plan(snap, [Assignment("P1", "R1", 5, 5, 0), Assignment("P1", NEW), Assignment("P2", NEW)])
    assert "DUPLICATE_PART" in codes(dup) and not dup.valid
    missing = validate_plan(snap, [Assignment("P1", "R1", 5, 5, 0)])
    assert codes(missing) == {"MISSING_PART"} and missing.missing_part_ids == ["P2"]
    # the official script does not flag a missing part as an error, ours blocks the export
    stock, orders, mats = official_rows(snap)
    _, _, _, bad = OFFICIAL.check(stock, orders, [{"part_id": "P1", "remnant_id": "R1", "x_mm": "5", "y_mm": "5",
                                                   "rot": "0"}], mats)
    assert bad == []


def test_t12_extra_unknown_dataset_scope_and_new_coordinates():
    snap = make_snapshot([("R1", "clear-4", 500, 500, False)], [("P1", "O1", "clear-4", 100, 100, False)])
    report = validate_plan(snap, [Assignment("P1", "R9", 5, 5, 0), Assignment("PX", NEW)])
    assert codes(report) == {"UNKNOWN_REMNANT", "UNKNOWN_PART"}
    report = validate_plan(snap, [Assignment("P1", NEW, 5, 5, 0)])
    assert codes(report) == {"NEW_WITH_COORDINATES"}
    report = validate_plan(snap, [Assignment("P1", "R1", 5, 5, 0)], unavailable_remnant_ids=["R1"])
    assert codes(report) == {"REMNANT_UNAVAILABLE"}
    report = validate_plan(snap, [Assignment("P1", "R1", None, 5, 0)])
    assert codes(report) == {"MISSING_COORDINATES"}


def test_strict_csv_parsing_rejects_float_and_negative_values():
    rows = [
        {"part_id": "P1", "remnant_id": "R1", "x_mm": "5.0", "y_mm": "5", "rot": "0"},
        {"part_id": "P2", "remnant_id": "R1", "x_mm": "-5", "y_mm": "5", "rot": "0"},
        {"part_id": "P3", "remnant_id": "R1", "x_mm": "5", "y_mm": "5", "rot": "2"},
        {"part_id": "P4", "remnant_id": "NEW", "x_mm": "", "y_mm": "", "rot": ""},
        {"part_id": "P5", "remnant_id": "", "x_mm": "", "y_mm": "", "rot": ""},
    ]
    parsed, issues = parse_solution_rows(rows)
    assert [a.part_id for a in parsed] == ["P4"]
    assert [i.code for i in issues] == ["NON_INTEGER_VALUE", "NEGATIVE_VALUE", "INVALID_ROTATION", "EMPTY_FIELD"]


def test_locks_are_enforced_by_validator():
    snap = make_snapshot([("R1", "clear-4", 500, 500, False), ("R2", "clear-4", 500, 500, False)],
                         [("P1", "O1", "clear-4", 100, 100, False)])
    lock = Assignment("P1", "R1", 5, 5, 0, "placement")
    assert validate_plan(snap, [Assignment("P1", "R1", 5, 5, 0)], locks=[lock]).valid
    assert codes(validate_plan(snap, [Assignment("P1", "R1", 6, 5, 0)], locks=[lock])) == {"LOCK_VIOLATED"}
    assign = Assignment("P1", "R1", lock_kind="assignment")
    assert validate_plan(snap, [Assignment("P1", "R1", 50, 50, 1)], locks=[assign]).valid
    assert codes(validate_plan(snap, [Assignment("P1", "R2", 5, 5, 0)], locks=[assign])) == {"LOCK_VIOLATED"}
