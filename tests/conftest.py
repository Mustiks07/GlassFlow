from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from glassflow.core.registry import Services
from glassflow.main import create_app

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "inputs" / "PACK_for_teams"
SOURCE_FILES = ["1_ostatki/materials.csv", "1_ostatki/stock_open.csv", "1_ostatki/orders_open.csv",
                "2_assistant_crm/questions_open.csv", "2_assistant_crm/dialogs_open.csv",
                "2_assistant_crm/applications_open.csv", "2_assistant_crm/ksm_knowledge_base.json"]


@pytest.fixture
def services():
    return Services()


@pytest.fixture
def client(tmp_path, services):
    with TestClient(create_app(tmp_path, services, testing=True)) as connection:
        connection.get("/api/v1/health")
        yield connection


@pytest.fixture
def uploads():
    return [(Path(p).name, (INPUTS / p).read_bytes()) for p in SOURCE_FILES]


def import_dataset(client, uploads, key="import", mode="source"):
    response = client.post("/api/v1/imports/preview", files=[("files", (n, c)) for n, c in uploads])
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["errors"] == [], report
    response = client.post(f"/api/v1/imports/{report['import_id']}/commit", json={"name": "Учебный", "mode": mode},
                           headers={"Idempotency-Key": key})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def imported(client, uploads):
    return import_dataset(client, uploads)
