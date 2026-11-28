import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from glassflow.contracts.common import Dimensions
from glassflow.core.registry import Services
from glassflow.main import create_app


def test_health_and_honest_readiness(tmp_path):
    with TestClient(create_app(tmp_path, Services(), testing=True)) as client:
        assert client.get("/api/v1/health").json()["app"] == "GlassFlow"
        readiness = client.get("/api/v1/ready").json()
        assert readiness["status"] == "degraded"
        assert readiness["database"] and readiness["schema"] and readiness["worker"]
        assert readiness["business_modules_ready"] is False
        response = client.get("/api/v1/datasets")
        assert response.status_code == 200
        assert response.json() == []
    assert (tmp_path / "glassflow.db").is_file()


@pytest.mark.parametrize("value", [1.5, "20", True, 0, -3])
def test_dimensions_are_positive_integer_millimetres(value):
    with pytest.raises(ValidationError):
        Dimensions(length_mm=value, width_mm=100)


def test_openapi_is_current():
    root = Path(__file__).resolve().parents[1]
    stored = json.loads((root / "packages/contracts/openapi.json").read_text(encoding="utf-8"))
    assert stored == create_app().openapi()
