"""Contract checks: migration snapshot, port conformance, DTO strictness, source parsing errors."""

import pytest
from pydantic import ValidationError

from glassflow.contracts.cutting import NewRemnant, Placement, SolverConfig
from glassflow.modules.cutting.conversion import input_from_snapshot
from glassflow.modules.cutting.engine import CuttingEngine, CuttingPortAdapter
from glassflow.modules.cutting.migrations import SNAPSHOT, render_ddl
from glassflow.modules.cutting.source_io import read_csv_text, rows_to_snapshot
from glassflow.ports import CuttingPort

from .conftest import make_snapshot


def test_migration_snippet_matches_models():
    assert SNAPSHOT.read_text(encoding="utf-8") == render_ddl(), "run write_snapshot() after model changes"


def test_engine_implements_cutting_port_and_validates_foreign_plans():
    port: CuttingPort = CuttingPortAdapter(session_factory=None)
    snap = make_snapshot([("R1", "clear-4", 300, 300, False)], [("P1", "O1", "clear-4", 100, 100, False)])
    data = input_from_snapshot(snap, config=SolverConfig(profile="quick", minimum_free_remnants=0))
    plan = port.solve(data, None)
    assert port.validate(data, plan).valid
    broken = plan.model_copy(update={"placements": [Placement(part_id="P1", remnant_id="R1", x_mm=0, y_mm=0, rot=0)]})
    result = CuttingEngine().validate(data, broken)
    assert not result.valid and result.issues[0].code == "OUT_OF_BOUNDS"


@pytest.mark.parametrize("value", [0, -1, 1.5, "10"])
def test_new_remnant_requires_positive_integer_mm(value):
    with pytest.raises(ValidationError):
        NewRemnant(dataset_id="d", material_id="clear-4", dimensions={"length_mm": value, "width_mm": 10},
                   defect=False, location_raw="A")


def test_source_rows_report_every_error_without_silent_fixes():
    materials = read_csv_text("material_id,название,толщина_мм,цена_нового_стекла_тг_за_м2,закалённое\n"
                              "clear-4,Стекло,4,4500,0\n".encode("utf-8-sig"))
    stock = read_csv_text("remnant_id,material_id,длина_мм,ширина_мм,возраст_дней,дефект,место\n"
                          "R1,clear-4,500,400,10,0,A\nR1,clear-4,500,400,10,0,A\nR2,zzz,500,400,1,0,A\n"
                          "R3,clear-4,-5,400,1,0,A\nR4,clear-4,500.5,400,1,2,A\n".encode())
    orders = read_csv_text("order_id,part_id,material_id,длина_мм,ширина_мм,премиум,тип_изделия\n"
                           "O1,P1,clear-4,100,100,0,x\nO1,P2,unknown,100,100,0,x\n".encode())
    snap, errors = rows_to_snapshot("d", materials, stock, orders)
    got = {(e.row, e.field, e.code) for e in errors}
    assert (3, "remnant_id", "DUPLICATE_ID") in got
    assert (4, "material_id", "UNKNOWN_MATERIAL") in got
    assert (5, "длина_мм", "NEGATIVE_OR_ZERO") in got
    assert (6, "длина_мм", "NOT_INTEGER") in got and (6, "дефект", "NOT_BINARY") in got
    assert (3, "material_id", "UNKNOWN_MATERIAL") in {(e.row, e.field, e.code) for e in errors if e.file == "orders.csv"}
    assert list(snap.remnants) == ["R1"]
    assert list(snap.parts) == ["P1", "P2"]  # unknown material keeps the part (it must be NEW), never dropped
