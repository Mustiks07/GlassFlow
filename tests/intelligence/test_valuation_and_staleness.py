"""Valuation helper (separate purpose) and T23 stale inventory before confirmation."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from glassflow.contracts.cutting import Candidate, Candidates
from glassflow.main import create_app
from glassflow.modules.intelligence.service import IntelligenceService
from glassflow.modules.intelligence.sources import InMemorySources
from glassflow.modules.intelligence.valuation import material_replacement_valuation, remnant_card_price

from .conftest import KB_PATH, MATERIALS_PATH


def test_material_valuation_matches_research_reference_formula():
    # 110.7532 m² of clear glass mix is not reproduced here; the formula itself: area × rate.
    value = material_replacement_valuation(166_500, Decimal("8000"))
    assert value.amount_tg == Decimal("1332.00") and value.purpose == "material_replacement_valuation"


@pytest.mark.parametrize("factor", ["0.30", "0.50", "0.70"])
def test_card_price_bounds_after_rounding(factor):
    value = remnant_card_price(460, 380, Decimal("8000"), Decimal(factor))
    full = Decimal(460 * 380) / Decimal(1_000_000) * Decimal(8000)
    assert full * Decimal("0.30") <= value.amount_tg <= full * Decimal("0.70")
    assert value.amount_tg.as_tuple().exponent == -2


def test_card_factor_outside_range_rejected():
    with pytest.raises(ValueError):
        remnant_card_price(460, 380, Decimal("8000"), Decimal("0.71"))


class VersionedInventory:
    """Test double: remnant R006 changes version after the first check (someone reserved it)."""

    def __init__(self):
        self.calls = 0

    def find_candidates(self, request):
        self.calls += 1
        if self.calls == 1:
            candidates = [Candidate(remnant_id="R006", remnant_version=1, x_mm=5, y_mm=5, rot=0, location_raw="Стеллаж A, ячейка 6")]
        else:
            candidates = []
        return Candidates(candidates=candidates, reason_codes=[] if candidates else ["no_free_whole_remnant"], scope="free_whole_remnants")


def test_t23_inventory_rechecked_before_confirmation(tmp_path):
    app = create_app(tmp_path, testing=True)
    with TestClient(app) as client:
        client.get("/api/v1/health")
        sources = InMemorySources()
        sources.add_kb("ds", KB_PATH.read_bytes())
        sources.set_materials("ds", MATERIALS_PATH.read_bytes())
        inventory = VersionedInventory()
        app.state.intelligence_service = IntelligenceService(sources, app.state.session_factory, inventory=inventory)
        version = client.get("/api/v1/catalog/versions", params={"dataset_id": "ds"}).json()[0]["kb_version"]
        quote = client.post("/api/v1/quotes", json={
            "dataset_id": "ds", "catalog_product_id": "steklo-6-prozrachnoe", "dimensions": {"length_mm": 450, "width_mm": 370},
            "quantity": 1, "processing": {"kind": "euro_edge", "sides": "all"}, "kb_version": version,
            "inventory_mode": "free_whole_remnants",
        }).json()
        assert quote["inventory_status"] == "checked" and quote["candidate_refs"][0]["remnant_id"] == "R006"
        confirmed = client.post(f"/api/v1/quotes/{quote['quote_id']}/confirm",
                                json={"dataset_id": "ds", "expected_revision": 1, "confirmed_by": "M1"}).json()
        assert confirmed["status"] == "confirmed"
        assert "candidate_changed_recheck_required" in confirmed["inventory_reason_codes"]
        assert confirmed["candidate_refs"] == []  # the old text/candidate does not confirm availability
        assert inventory.calls == 2
