from fastapi.testclient import TestClient

from backend.app.main import app


def test_health_baseline_and_admin_protection():
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        baseline = client.get("/api/baseline?duration_hours=1")
        assert baseline.status_code == 200
        assert baseline.json()["impact_label"] == "SIMULATED IMPACT"

        payload = {
            "name": "x",
            "interventions": [],
            "duration_hours": 1,
            "seed": 1,
            "parameters": {},
        }
        denied = client.post("/api/scenarios/run", json=payload)
        assert denied.status_code == 403

        allowed = client.post(
            "/api/scenarios/run",
            headers={"X-Admin-Token": "test-token"},
            json=payload,
        )
        assert allowed.status_code == 200


def test_telemetry_api_persists_and_rejects_duplicate():
    from backend.app.db import SessionLocal, TelemetryRecord
    from factory_simulator import FactorySimulator, baseline_config

    simulator = FactorySimulator(baseline_config(1), seed=66)
    simulator.run()
    event = simulator.telemetry[0]

    with TestClient(app) as client:
        first = client.post("/api/telemetry", json=event)
        assert first.status_code == 200 and first.json()["accepted"] is True
        second = client.post("/api/telemetry", json=event)
        assert second.status_code == 200 and second.json()["duplicate"] is True

    with SessionLocal() as db:
        count = db.query(TelemetryRecord).filter(TelemetryRecord.event_id == event["event_id"]).count()
        assert count == 1
