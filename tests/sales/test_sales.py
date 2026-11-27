"""All buyers and domain adapters here are synthetic; no real registry is claimed."""
import csv
import io
import json
from decimal import Decimal

import pytest

from glassflow.contracts.cutting import CutMetrics, CutPlan, Dimensions, Remnant, ValidationResult
from glassflow.modules.platform.imports import records
from glassflow.modules.sales.service import BUYER_FIELDS, card_price


def synthetic_registry():
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=BUYER_FIELDS)
    writer.writeheader()
    evidence = []
    categories = ["мебельная фабрика", "дизайн-студия", "магазин", "салон", "строительная компания"]
    for i in range(50):
        row = dict(name=f"Синтетическая организация {i}", city="Астана", category=categories[i % 5],
                   url=f"https://synthetic{i}.example.test", why="Возможные вставки из стекла и зеркал",
                   source_url=f"https://synthetic{i}.example.test/about", score=50 + i)
        writer.writerow(row)
        evidence.append({"name": row["name"], "city": row["city"], "profile": "Синтетический тестовый профиль",
                         "source_url": row["source_url"], "checked_at": "2026-11-27", "reviewer": "pytest",
                         "confirmation": "Synthetic data, not a real public organization", "entity_id": f"TEST{i}"})
    return output.getvalue().encode("utf8"), json.dumps({"records": evidence,
        "dedupe_policy": "Synthetic unique fixture entities"}, ensure_ascii=False).encode("utf8")


class SyntheticSource:
    revision = 1
    unavailable = set()

    def get_plan(self, session, dataset_id, plan_id):
        return CutPlan(dataset_id=dataset_id, plan_id=plan_id, revision=self.revision, status="validated",
            placements=[], metrics=CutMetrics(covered_area_mm2=0, total_area_mm2=1, coverage=0,
                replacement_value_tg="0", invalid=0, missing=0, fully_covered_orders=0),
            free_original_remnant_ids=[r.public_id for r in records(session, dataset_id, "stock")], search_status="feasible")

    def validate_plan(self, session, dataset_id, plan):
        return ValidationResult(valid=True, errors=[], invalid_part_ids=[], missing_part_ids=[])

    def get_remnant(self, session, dataset_id, rid):
        row = next(r.data for r in records(session, dataset_id, "stock") if r.public_id == rid)
        return Remnant(dataset_id=dataset_id, remnant_id=rid, material_id=row["material_id"],
                       dimensions=Dimensions(length_mm=int(row["длина_мм"]), width_mm=int(row["ширина_мм"])),
                       defect=row["дефект"] == "1", location_raw=row["место"],
                       status="reserved" if rid in self.unavailable else "available", version=0)


def import_synthetic_buyers(client, dataset_id):
    content, evidence = synthetic_registry()
    response = client.post("/api/v1/buyers/import", params={"dataset_id": dataset_id},
                           files={"file": ("buyers.csv", content), "evidence": ("evidence.json", evidence)},
                           headers={"Idempotency-Key": "buyers"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "verified", response.text
    return response.json()["version"]


@pytest.mark.parametrize("factor", ["0.30", "0.50", "0.70"])
@pytest.mark.parametrize("dims,rate", [((1000, 1000), "10000"), ((1, 1), "1"), ((450, 370), "8000")])
def test_decimal_boundaries_after_rounding(factor, dims, rate):
    price = Decimal(card_price(*dims, rate, factor))
    full = Decimal(dims[0]) * Decimal(dims[1]) / 1_000_000 * Decimal(rate)
    assert full * Decimal(".30") <= price <= full * Decimal(".70")


def test_registry_cards_exact_top3_stale_and_price(client, imported, services):
    d = imported["dataset_id"]
    version = import_synthetic_buyers(client, d)
    source = SyntheticSource()
    services.sales_source = source
    body = dict(dataset_id=d, plan_id="synthetic-plan", plan_revision=1, buyer_registry_version=version)
    response = client.post("/api/v1/sale-cards", json=body, headers={"Idempotency-Key": "cards"})
    assert response.status_code == 200, response.text
    cards = response.json()
    assert len(cards) == len({c["remnant_id"] for c in cards}) == 5
    assert all(c["status"] == "ready" and len(set(c["top3_buyer_ids"])) == 3 for c in cards)
    source.revision = 2
    stale = client.get("/api/v1/sale-cards", params={"dataset_id": d}).json()
    assert all(c["status"] == "stale" for c in stale)
    body["plan_revision"] = 2
    source.unavailable = {r["remnant_id"] for r in cards}
    fresh = client.post("/api/v1/sale-cards", json=body, headers={"Idempotency-Key": "fresh"}).json()
    assert not source.unavailable & {c["remnant_id"] for c in fresh}
