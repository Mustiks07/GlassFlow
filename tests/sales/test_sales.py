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
        row = dict(
            name=f"Синтетическая организация {i}",
            city="Астана",
            category=categories[i % 5],
            url=f"https://synthetic{i}.example.test",
            why="Возможные вставки из стекла и зеркал",
            source_url=f"https://synthetic{i}.example.test/about",
            score=50 + i,
        )
        writer.writerow(row)
        evidence.append(
            {
                "name": row["name"],
                "city": row["city"],
                "profile": "Синтетический тестовый профиль",
                "source_url": row["source_url"],
                "checked_at": "2026-11-27",
                "reviewer": "pytest",
                "confirmation": "Synthetic data, not a real public organization",
                "entity_id": f"TEST{i}",
                "applications": [{
                    "application": "finished_panel", "material_ids": ["clear-4", "clear-6", "clear-8",
                        "grey-8", "bronze-8", "mirror-4", "temp-4", "temp-6"],
                    "min_dimensions": {"length_mm": 1, "width_mm": 1}, "requires_cutting": False,
                    "dimensions_basis": "Explicit synthetic size assumption; not public buyer demand",
                    "activity": "Synthetic test organization makes ready-size panels",
                    "source_url": row["source_url"], "checked_at": "2026-11-27",
                }],
            }
        )
    return output.getvalue().encode("utf8"), json.dumps(
        {"records": evidence, "dedupe_policy": "Synthetic unique fixture entities"}, ensure_ascii=False
    ).encode("utf8")


class SyntheticSource:
    revision = 1
    unavailable = set()

    def get_plan(self, session, dataset_id, plan_id):
        return CutPlan(
            dataset_id=dataset_id,
            plan_id=plan_id,
            revision=self.revision,
            status="validated",
            placements=[],
            metrics=CutMetrics(
                covered_area_mm2=0,
                total_area_mm2=1,
                coverage=0,
                replacement_value_tg="0",
                invalid=0,
                missing=0,
                fully_covered_orders=0,
            ),
            free_original_remnant_ids=[r.public_id for r in records(session, dataset_id, "stock")],
            search_status="feasible",
        )

    def validate_plan(self, session, dataset_id, plan):
        return ValidationResult(valid=True, errors=[], invalid_part_ids=[], missing_part_ids=[])

    def get_remnant(self, session, dataset_id, rid):
        row = next(r.data for r in records(session, dataset_id, "stock") if r.public_id == rid)
        return Remnant(
            dataset_id=dataset_id,
            remnant_id=rid,
            material_id=row["material_id"],
            dimensions=Dimensions(length_mm=int(row["длина_мм"]), width_mm=int(row["ширина_мм"])),
            defect=row["дефект"] == "1",
            location_raw=row["место"],
            status="reserved" if rid in self.unavailable else "available",
            version=0,
        )


def import_synthetic_buyers(client, dataset_id):
    content, evidence = synthetic_registry()
    response = client.post(
        "/api/v1/buyers/import",
        params={"dataset_id": dataset_id},
        files={"file": ("buyers.csv", content), "evidence": ("evidence.json", evidence)},
        headers={"Idempotency-Key": "buyers"},
    )
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


def test_u03_mirror_to_tempered_replaces_explanations_and_rejects_cutting(client, imported, services):
    d = imported["dataset_id"]
    source = SyntheticSource()
    source.unavailable = set()
    services.sales_source = source
    content, proof = synthetic_registry()
    proof = json.loads(proof)
    for i, item in enumerate(proof["records"]):
        base = item["applications"][0]
        if i < 3:
            base.update(application="mirror_interior", material_ids=["mirror-4"], requires_cutting=True,
                        activity="Synthetic evidence: makes furniture mirrors")
        elif i < 6:
            base.update(application="finished_panel", material_ids=["temp-6"], requires_cutting=False,
                        activity="Synthetic evidence: installs ready-size tempered panels")
        elif i == 6:
            # It even names tempered, but cutting is unsafe and must exclude it.
            base.update(material_ids=["temp-6"], requires_cutting=True)
        else:
            base.update(material_ids=["clear-4"])
    response = client.post("/api/v1/buyers/import", params={"dataset_id": d},
        files={"file": ("buyers.csv", content), "evidence": ("evidence.json", json.dumps(proof).encode())},
        headers={"Idempotency-Key": "u03-evidence"})
    version = response.json()["version"]
    assert response.json()["status"] == "verified"
    with client.app.state.session_factory() as session:
        stock = list(records(session, d, "stock"))
        mirror = next(r.public_id for r in stock if r.data["material_id"] == "mirror-4")
        tempered = next(r.public_id for r in stock if r.data["material_id"] == "temp-6")
    def matches(rid):
        return client.get("/api/v1/buyers/matches", params=dict(dataset_id=d, version=version, remnant_id=rid)).json()
    mirrors, panels = matches(mirror), matches(tempered)
    assert {m["name"] for m in mirrors} == {f"Синтетическая организация {i}" for i in range(3)}
    assert {m["name"] for m in panels} == {f"Синтетическая организация {i}" for i in range(3, 6)}
    assert all("подрезка запрещена" in " ".join(m["constraints"]) for m in panels)
    assert all(not m["interest_confirmed"] and m["source_url"] and m["checked_at"] for m in panels)
    assert all(m["registry_version"] == version and m["material_id"] == "temp-6" for m in panels)
    source.unavailable = {tempered}
    assert matches(tempered) == []


def test_u03_absent_or_wrong_size_evidence_never_falls_back_to_keywords(client, imported, services):
    d = imported["dataset_id"]
    services.sales_source = SyntheticSource()
    services.sales_source.unavailable = set()
    content, proof = synthetic_registry()
    proof = json.loads(proof)
    for item in proof["records"]:
        item["applications"][0]["min_dimensions"] = dict(length_mm=100000, width_mm=100000)
    response = client.post("/api/v1/buyers/import", params={"dataset_id": d},
        files={"file": ("buyers.csv", content), "evidence": ("evidence.json", json.dumps(proof).encode())},
        headers={"Idempotency-Key": "u03-no-size"})
    version = response.json()["version"]
    result = client.post("/api/v1/sale-cards", json=dict(dataset_id=d, plan_id="synthetic-plan",
                         plan_revision=1, buyer_registry_version=version),
                         headers={"Idempotency-Key": "u03-no-cards"})
    assert result.status_code == 409 and result.json()["code"] == "BUYER_MATCHES_REQUIRED"
    assert client.get("/api/v1/sale-cards", params={"dataset_id": d}).json() == []
    proof["records"][0]["applications"][0]["source_url"] = "https://wrong.example.test"
    invalid = client.post("/api/v1/buyers/import", params={"dataset_id": d},
        files={"file": ("buyers.csv", content), "evidence": ("evidence.json", json.dumps(proof).encode())},
        headers={"Idempotency-Key": "u03-invalid-proof"}).json()
    assert invalid["status"] == "needs_review"
