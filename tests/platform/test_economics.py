"""U07 synthetic arithmetic/API/PDF acceptance only; these are not human labor measurements."""

import io
from copy import deepcopy

from pypdf import PdfReader
from test_reports import synthetic_evidence

from glassflow.modules.platform.economics import serialized_result


def create(client, imported):
    inputs = synthetic_evidence()["economics"]
    response = client.post("/api/v1/economics/scenarios", json=dict(
        dataset_id=imported["dataset_id"], name="Synthetic calculation test", inputs=inputs),
        headers={"Idempotency-Key": "econ-create"})
    assert response.status_code == 200, response.text
    return response.json()


def test_u07_same_snapshot_for_api_pdf_history_and_sensitivity(client, imported):
    original = create(client, imported)
    d, sid = original["dataset_id"], original["scenario_id"]
    assert original["results"]["scenario_net_effect_tg"] == "10000"
    assert original["competition_release_eligible"] is False
    inputs = deepcopy(original["inputs"])
    inputs.update(material_use_fraction="0.25", material_use_basis="Synthetic sensitivity assumption",
                  confirmed_material_use_value_tg="12345", confirmed_material_use_ref="synthetic-use",
                  potential_remnant_sale_tg="500000", actual_sale_revenue_tg="1000000", actual_sale_ref="synthetic-sale")
    inputs["sensitivity"] = {"material_use_fraction": {"low": "0.10", "high": "0.50"}}
    url = f"/api/v1/economics/scenarios/{sid}"
    body = dict(dataset_id=d, expected_version=0, inputs=inputs)
    response = client.put(url, json=body, headers={"Idempotency-Key": "econ-update"})
    assert response.status_code == 200, response.text
    new = response.json()
    assert new["results"] == serialized_result(inputs)
    assert new["results"]["scenario_net_effect_tg"] == "2500"
    assert new["results"]["payback_months"] == "5.6"
    assert new["results"]["net_range_low_tg"] == "1000"
    assert new["results"]["net_range_high_tg"] == "5000"
    assert client.put(url, json=body, headers={"Idempotency-Key": "econ-update"}).json() == new
    assert client.put(url, json=body, headers={"Idempotency-Key": "econ-conflict"}).status_code == 409
    for snapshot in (original, new):
        params = dict(dataset_id=d, version=snapshot["version"])
        assert client.get(url, params=params).json() == snapshot
        pdf = client.get(url + "/pdf", params=params)
        assert pdf.status_code == 200, pdf.text[:500] if pdf.status_code != 200 else ""
        assert pdf.headers["X-GlassFlow-Result-Hash"] == snapshot["result_hash"]
        reader = PdfReader(io.BytesIO(pdf.content))
        assert len(reader.pages) == 1
        text = reader.pages[0].extract_text()
        assert snapshot["result_hash"] in text.replace("\n", "")
        assert "НЕ ФИНАЛЬНАЯ ЗАПИСКА" in text
        assert ("2 500.00" if snapshot["version"] == 1 else "10 000.00") in text


def test_u07_nonpositive_effect_and_bad_measurement_provenance(client, imported):
    original = create(client, imported)
    inputs = original["inputs"]
    inputs["hosting_monthly_tg"] = "1000000"
    result = serialized_result(inputs)
    assert result["payback_months"] is None
    assert result["net_range_high_tg"].startswith("-")
    base = dict(dataset_id=original["dataset_id"], name="Invalid synthetic input", inputs=inputs)
    for field, value in (("manual_active_seconds", "100000"), ("manual_rework_seconds", "10000"),
                         ("app_started_at", "2026-11-27T09:00:00"), ("operator", "")):
        body = deepcopy(base)
        body["inputs"]["labor_studies"][0][field] = value
        assert client.post("/api/v1/economics/scenarios", json=body,
                            headers={"Idempotency-Key": field}).status_code == 422
    inputs["labor_studies"] = inputs["labor_studies"][:9]
    assert client.post("/api/v1/economics/scenarios", json=base,
                       headers={"Idempotency-Key": "only-nine"}).status_code == 422
