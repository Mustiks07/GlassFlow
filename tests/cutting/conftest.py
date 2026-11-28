"""Fixtures for cutting tests. Synthetic data here is TEST data, not organisers' hidden data."""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from glassflow.contracts.platform import Job
from glassflow.main import create_app
from glassflow.modules.cutting.domain import MaterialSpec, PartSpec, RemnantSpec, Snapshot
from glassflow.modules.cutting.engine import CuttingEngine
from glassflow.modules.cutting.service import CuttingService
from glassflow.modules.cutting.source_io import load_pack
from glassflow.modules.cutting.uow import write_transaction

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "inputs" / "PACK_for_teams" / "1_ostatki"


def official_module():
    """The UNMODIFIED organisers' validate.py loaded as a module (its check() is what the jury runs)."""
    spec = importlib.util.spec_from_file_location("official_validate", PACK / "validate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def official_rows(snapshot: Snapshot):
    stock = [{"remnant_id": r.remnant_id, "material_id": r.material_id, "длина_мм": str(r.length_mm),
              "ширина_мм": str(r.width_mm), "возраст_дней": str(r.age_days or 0), "дефект": "1" if r.defect else "0",
              "место": r.location_raw} for r in (snapshot.remnants[x] for x in snapshot.remnant_order)]
    orders = [{"order_id": p.order_id, "part_id": p.part_id, "material_id": p.material_id, "длина_мм": str(p.length_mm),
               "ширина_мм": str(p.width_mm), "премиум": "1" if p.premium else "0", "тип_изделия": p.product_type}
              for p in (snapshot.parts[x] for x in snapshot.part_order)]
    mats = [{"material_id": m.material_id, "название": m.name, "толщина_мм": str(m.thickness_mm),
             "цена_нового_стекла_тг_за_м2": str(m.price_per_m2), "закалённое": "1" if m.tempered else "0"}
            for m in snapshot.materials.values()]
    return stock, orders, mats


@pytest.fixture(scope="session")
def open_snapshot() -> Snapshot:
    return load_pack(PACK)


def make_snapshot(remnants, parts, dataset_id="synthetic-test", materials=None) -> Snapshot:
    """remnants: (id, material, L, W, defect[, age]); parts: (id, order, material, L, W, premium)."""
    materials = materials or {
        "clear-4": MaterialSpec("clear-4", False, Decimal("4500"), "Стекло 4", 4),
        "mirror-4": MaterialSpec("mirror-4", False, Decimal("9500"), "Зеркало 4", 4),
        "temp-6": MaterialSpec("temp-6", True, Decimal("15000"), "Калёное 6", 6),
    }
    rs = {}
    for row in remnants:
        rid, mid, length, width, defect = row[:5]
        age = row[5] if len(row) > 5 else 10
        rs[rid] = RemnantSpec(rid, mid, length, width, defect, age, "available", 0, f"Стеллаж T, ячейка {rid}", True)
    ps = {pid: PartSpec(pid, oid, mid, length, width, premium) for pid, oid, mid, length, width, premium in parts}
    return Snapshot(dataset_id, materials, rs, ps)


class InlineJobSubmitter:
    """TEST-ONLY stand-in for the platform queue: runs the real engine inline and stores via the service."""

    def __init__(self, app, fail: bool = False):
        self.app = app
        self.fail = fail
        self.jobs: dict[str, Job] = {}

    def submit(self, kind: str, dataset_id: str, payload: dict) -> Job:
        from glassflow.contracts.cutting import SolveInput

        job_id = f"job-{len(self.jobs) + 1}"
        if self.fail:
            job = Job(job_id=job_id, state="failed", stage="solve", error_code="SOLVER_CRASHED")
        else:
            plan = CuttingEngine().solve(SolveInput.model_validate(payload), None)
            with write_transaction(self.app.state.session_factory) as session:
                stored = CuttingService(session).store_solver_plan(dataset_id, plan, base_plan_id=None)
            job = Job(job_id=job_id, state="completed", stage="done", result_ref=f"{stored.plan_id}@{stored.revision}")
        self.jobs[job_id] = job
        return job


@pytest.fixture()
def app_client(tmp_path):
    app = create_app(tmp_path, testing=True)
    with TestClient(app) as client:
        client.get("/api/v1/health")
        yield app, client


def register(app, dataset_id: str, snapshot: Snapshot, mode: str = "workspace") -> None:
    snap = Snapshot(dataset_id, snapshot.materials, snapshot.remnants, snapshot.parts, snapshot.part_order,
                    snapshot.remnant_order)
    with write_transaction(app.state.session_factory) as session:
        CuttingService(session).register_dataset(dataset_id, mode, snap)
