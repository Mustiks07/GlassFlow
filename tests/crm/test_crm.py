import csv
import io

import pytest
from conftest import import_dataset


def test_unknown_complaint_does_not_become_observed_zero():
    from glassflow.modules.crm.service import rank_rows
    common = {"client_id": "SYNTHETIC-C", "прошлых_заявок": "2", "manager": "M1",
              "дней_с_последнего_контакта": "10"}
    rows = [{**common, "app_id": "SYNTHETIC-UNKNOWN", "жалоба": None}]
    rows += [{**common, "app_id": f"SYNTHETIC-KNOWN-{i}", "жалоба": "0"} for i in range(25)]
    result = rank_rows(rows)
    assert "SYNTHETIC-UNKNOWN" not in [r.app_id for r in result.rows]
    assert rows[0]["жалоба"] is None


def test_baseline_exact_open_and_no_label_leak(client, imported, uploads):
    d = imported["dataset_id"]
    result = client.post("/api/v1/crm/rank", json={"dataset_id": d}).json()
    original = list(csv.DictReader(io.StringIO(dict(uploads)["applications_open.csv"].decode("utf8"))))
    expected = sorted(
        original,
        key=lambda r: (
            -int(r["прошлых_заявок"]),
            int(r["жалоба"]),
            r["manager"] == "M4",
            int(r["дней_с_последнего_контакта"]),
        ),
    )[:25]
    assert [r["app_id"] for r in result["rows"]] == [r["app_id"] for r in expected]
    assert result["observed_precision"] == 0.8
    assert result["unique_client_count"] == len({r["client_id"] for r in expected})
    assert sum(map(len, result["grouped_clients"].values())) == 25
    output = io.StringIO(newline="")
    fields = [k for k in original[0] if k != "вернулся_за_60_дней"]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(original)
    without = [
        (n, output.getvalue().encode("utf8") if n == "applications_open.csv" else c) for n, c in uploads
    ]
    closed = import_dataset(client, without, "closed", "contest")
    hidden = client.post("/api/v1/crm/rank", json={"dataset_id": closed["dataset_id"]}).json()
    assert hidden["rows"] == result["rows"] and hidden["observed_precision"] is None
    dashboard = client.get("/api/v1/analytics/managers", params={"dataset_id": closed["dataset_id"]}).json()
    assert all(m["returns"]["value"] is None and m["returns"]["denominator"] == 0 for m in dashboard)


def test_metrics_known_denominators_filters_and_immutable_history(client, imported):
    d = imported["dataset_id"]
    result = client.get("/api/v1/analytics/managers", params={"dataset_id": d}).json()
    assert len(result) == 5 and sum(r["application_count"] for r in result) == 700
    assert all(len(r["evidence"]) == 8 for r in result)
    for row in result:
        assert row["conversion"]["denominator"] == row["application_count"]
        assert len(row["evidence"]["conversion"]["known_app_ids"]) == row["application_count"]
        assert len(row["evidence"]["mean_sale_tg"]["known_app_ids"]) == row["conversion"]["numerator"]
    empty = client.get(
        "/api/v1/analytics/managers", params={"dataset_id": d, "channel": "not present"}
    ).json()
    assert all(r["application_count"] == 0 and r["mean_sale_tg"] is None for r in empty)
    client.post("/api/v1/crm/rank", json={"dataset_id": d})
    assert client.get("/api/v1/analytics/managers", params={"dataset_id": d}).json() == result


def test_reminder_recipient_uniqueness_utc_and_history(client, imported):
    d = imported["dataset_id"]
    body = dict(
        dataset_id=d,
        recipient_client_id="C115",
        source_app_ids=["A0001"],
        subject_type="interest",
        subject_ref="калёное",
        due_at="2026-12-01T12:00:00+05:00",
        owner="M1",
    )
    headers = {"Idempotency-Key": "reminder"}
    response = client.post("/api/v1/crm/reminders", json=body, headers=headers)
    assert response.status_code == 200, response.text
    reminder = response.json()
    assert reminder["due_at"] == "2026-12-01T07:00:00+00:00"
    again = client.post("/api/v1/crm/reminders", json=body, headers={"Idempotency-Key": "another"}).json()
    assert again["reminder_id"] == reminder["reminder_id"]
    action = dict(dataset_id=d, expected_version=0)
    url = f"/api/v1/crm/reminders/{reminder['reminder_id']}/confirm"
    confirmed = client.post(url, json=action, headers={"Idempotency-Key": "confirm"})
    assert confirmed.status_code == 200 and confirmed.json()["state"] == "scheduled"
    assert client.post(url, json=action, headers={"Idempotency-Key": "confirm"}).json() == confirmed.json()
    assert client.post(url, json=action, headers={"Idempotency-Key": "old"}).status_code == 409
    body["recipient_client_id"] = "not-owner"
    assert (
        client.post("/api/v1/crm/reminders", json=body, headers={"Idempotency-Key": "wrong"}).status_code
        == 422
    )
    body.update(recipient_client_id="C115", due_at="2026-12-01T12:00:00")
    assert client.post("/api/v1/crm/reminders", json=body, headers=headers).status_code == 422


@pytest.mark.parametrize("change", ["inventory", "quote"])
def test_remnant_stale_read_and_confirm(client, imported, services, change):
    class Resolver:
        version = 0
        compatibility_version = 0

        def check(self, session, dataset_id, subject_type, ref, expected, **kwargs):
            return {
                "valid": self.version == 0,
                "version": self.version,
                "reason": "Занят",
                "compatibility_version": self.compatibility_version,
                "compatibility_valid": True,
            }

    resolver = Resolver()
    services.subjects = resolver  # Explicit synthetic domain adapter, never production fallback.
    d = imported["dataset_id"]
    body = dict(
        dataset_id=d,
        recipient_client_id="C115",
        source_app_ids=["A0001"],
        subject_type="specific_remnant",
        subject_ref="R001",
        subject_version=0,
        compatibility_ref="synthetic-quote",
        compatibility_version=0,
        due_at="2026-12-01T12:00:00Z",
        owner="M1",
    )
    reminder = client.post("/api/v1/crm/reminders", json=body, headers={"Idempotency-Key": "new"}).json()
    if change == "inventory":
        resolver.version = 1
    else:
        resolver.compatibility_version = 1
    url = f"/api/v1/crm/reminders/{reminder['reminder_id']}"
    response = client.post(
        url + "/confirm",
        json={"dataset_id": d, "expected_version": 0},
        headers={"Idempotency-Key": "confirm"},
    )
    assert response.status_code == 409
    stale = client.get(url, params={"dataset_id": d}).json()
    assert stale["state"] == "stale" and stale["version"] == 1
