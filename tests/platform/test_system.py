from pathlib import Path

from fastapi.testclient import TestClient

from glassflow.main import create_app


def test_secret_session_only_budget_opt_in_and_restart(tmp_path):
    with TestClient(create_app(tmp_path, testing=True)) as client:
        token = client.get("/api/v1/session").json()["session_token"]
        owner = {"X-GlassFlow-Session": token}
        body = dict(api_key="synthetic-secret-should-never-persist", profile="direct", model_id="test-free")
        assert client.patch("/api/v1/settings", json=body).status_code == 403
        response = client.patch("/api/v1/settings", json=body, headers=owner)
        assert response.status_code == 200 and response.json()["secret_present"]
        assert "synthetic-secret" not in response.text
        assert (
            client.patch(
                "/api/v1/settings", json={"version": 1, "paid_enabled": True}, headers=owner
            ).status_code
            == 422
        )
        assert client.post("/api/v1/settings/ai/check", headers=owner).status_code == 503
    assert not any(b"synthetic-secret" in p.read_bytes() for p in Path(tmp_path).glob("*.db*"))
    with TestClient(create_app(tmp_path, testing=True)) as client:
        assert not client.get("/api/v1/settings").json()["secret_present"]


def test_online_backup_and_explicit_restore_preserves_prior_database(client, imported, tmp_path):
    token = client.get("/api/v1/session").json()["session_token"]
    owner = {"X-GlassFlow-Session": token}
    backup = client.post("/api/v1/system/backup", headers=owner).json()
    assert backup["integrity"] == "ok"
    client.post(
        f"/api/v1/datasets/{imported['dataset_id']}/working-copy",
        json={},
        headers={"Idempotency-Key": "later"},
    )
    assert len(client.get("/api/v1/datasets").json()) == 2
    response = client.post(
        "/api/v1/system/restore", json={"backup_id": "../outside", "confirm_replace": True}, headers=owner
    )
    assert response.status_code == 404
    response = client.post(
        "/api/v1/system/restore",
        json={"backup_id": backup["backup_id"], "confirm_replace": True},
        headers=owner,
    )
    assert response.status_code == 200 and response.json()["status"] == "pending_restart"
    assert client.post("/api/v1/runs", json={}).status_code == 503
    client.app.state.coordinator.stop()
    client.app.state.engine.dispose()
    # Close the old service before opening the restored database in a new lifecycle.
    with TestClient(create_app(tmp_path, testing=True)) as restored:
        datasets = restored.get("/api/v1/datasets").json()
        assert len(datasets) == 1 and datasets[0]["dataset_id"] == imported["dataset_id"]
    assert len(list((tmp_path / "backups").glob("*.db"))) >= 3
