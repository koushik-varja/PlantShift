from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import main as main_mod
from backend.app.db import SessionLocal, TelemetryRecord
from digital_twin import TwinStore
from factory_simulator import FactorySimulator, baseline_config
from ml import FailureRiskService
from optimizer import BusinessAssumptions, PortfolioConstraints, optimize_portfolio
from optimizer import portfolio as portfolio_mod
from telemetry import TelemetryIngestor


def _sample_machine_a_event() -> dict[str, Any]:
    sim = FactorySimulator(baseline_config(1), seed=808)
    sim.run()
    return deepcopy(next(event for event in sim.telemetry if event["machine_id"] == "machineA"))


def test_late_telemetry_does_not_pollute_runtime_ml_history(monkeypatch: pytest.MonkeyPatch) -> None:
    predictor = FailureRiskService(Path("ml/artifacts/failure_risk.joblib"))
    fresh_twins = TwinStore()
    fresh_ingestor = TelemetryIngestor(fresh_twins, predictor=predictor.predict)

    base = _sample_machine_a_event()
    t2 = datetime.fromisoformat(base["timestamp"])
    t1 = t2 - timedelta(minutes=1)
    t3 = t2 + timedelta(minutes=1)

    event_t2 = deepcopy(base)
    event_t2.update(event_id="late-ml-history-t2", timestamp=t2.isoformat(), temperature_c=53.0)
    event_t1 = deepcopy(base)
    event_t1.update(event_id="late-ml-history-t1", timestamp=t1.isoformat(), temperature_c=99.0)
    event_t3 = deepcopy(base)
    event_t3.update(event_id="late-ml-history-t3", timestamp=t3.isoformat(), temperature_c=54.0)

    with TestClient(main_mod.app) as client:
        monkeypatch.setattr(main_mod, "twins", fresh_twins)
        monkeypatch.setattr(main_mod, "ingestor", fresh_ingestor)

        first = client.post("/api/telemetry", json=event_t2)
        assert first.status_code == 200
        assert first.json()["accepted"] is True and first.json()["late"] is False

        twin_after_t2 = fresh_twins.get("machineA")
        assert twin_after_t2 is not None
        health_after_t2 = (
            twin_after_t2["health_state"],
            twin_after_t2["failure_probability"],
            twin_after_t2["feature_timestamp"],
        )
        assert [row["event_id"] for row in predictor._history["machineA"]] == ["late-ml-history-t2"]

        late = client.post("/api/telemetry", json=event_t1)
        assert late.status_code == 200
        assert late.json()["accepted"] is True and late.json()["late"] is True

        twin_after_t1 = fresh_twins.get("machineA")
        assert twin_after_t1 is not None
        assert twin_after_t1["updated_at"] == t2
        assert (
            twin_after_t1["health_state"],
            twin_after_t1["failure_probability"],
            twin_after_t1["feature_timestamp"],
        ) == health_after_t2
        assert [row["event_id"] for row in predictor._history["machineA"]] == ["late-ml-history-t2"]
        assert any(item["event_id"] == "late-ml-history-t1" for item in twin_after_t1["recent_telemetry"])

        with SessionLocal() as db:
            persisted_ids = {
                row[0]
                for row in db.query(TelemetryRecord.event_id)
                .filter(TelemetryRecord.event_id.in_(["late-ml-history-t2", "late-ml-history-t1"]))
                .all()
            }
        assert persisted_ids == {"late-ml-history-t2", "late-ml-history-t1"}

        third = client.post("/api/telemetry", json=event_t3)
        assert third.status_code == 200
        assert third.json()["accepted"] is True and third.json()["late"] is False

    assert [row["event_id"] for row in predictor._history["machineA"]] == [
        "late-ml-history-t2",
        "late-ml-history-t3",
    ]
    assert predictor._history["machineA"][0]["timestamp"] < predictor._history["machineA"][1]["timestamp"]


def test_no_action_wins_when_every_financial_transformation_is_negative() -> None:
    assumptions = BusinessAssumptions(
        value_per_finished_unit=0,
        downtime_cost_per_hour=0,
        scrap_cost_per_unit=0,
        rework_cost_per_unit=0,
        energy_cost_per_kwh=0,
        planned_maintenance_cost=0,
        unplanned_maintenance_cost=0,
    )
    result = optimize_portfolio(
        PortfolioConstraints(
            budget=1000,
            implementation_capacity=100,
            maximum_risk=100,
            objective="MAXIMIZE_ESTIMATED_VALUE",
            evaluation_runs=3,
            business_assumptions=assumptions,
        ),
        duration_hours=1,
        seed=9,
    )
    assert result["decision"] == "NO_ACTION"
    assert result["best"]["interventions"] == []
    assert result["best"]["estimated_value"]["estimated_net_value"]["median"] == 0
    assert all(candidate["interventions"] for candidate in result["alternatives"])
    assert "No transformation portfolio improves" in result["explanation"]["why"]


def _controlled_metrics(throughput: float) -> dict[str, Any]:
    return {
        "throughput_units": throughput,
        "oee": {"oee": 0.5},
        "unplanned_downtime_min": 10.0,
        "scrap_rate": 0.02,
        "energy_kwh": 100.0,
        "late_orders": 2,
        "scrap_units": 2,
        "rework_units": 1,
        "machines": {"machineA": {"maintenance_events": 0, "failures": 0}},
    }


def test_no_action_can_win_operational_objective_when_all_candidates_worsen(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(scenario, *, duration_hours: float, seed: int, **kwargs):
        del duration_hours, seed, kwargs
        return _controlled_metrics(100.0 if not scenario.interventions else 90.0)

    monkeypatch.setattr(portfolio_mod, "run_scenario", fake_run)
    result = optimize_portfolio(
        PortfolioConstraints(
            budget=1000,
            implementation_capacity=100,
            maximum_risk=100,
            objective="MAXIMIZE_THROUGHPUT",
            evaluation_runs=3,
        ),
        duration_hours=1,
        seed=2,
    )
    assert result["decision"] == "NO_ACTION"
    assert result["best"]["score"] == 0


def test_transformation_still_beats_no_action_when_objective_improves(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(scenario, *, duration_hours: float, seed: int, **kwargs):
        del duration_hours, seed, kwargs
        return _controlled_metrics(100.0 if not scenario.interventions else 110.0)

    monkeypatch.setattr(portfolio_mod, "run_scenario", fake_run)
    result = optimize_portfolio(
        PortfolioConstraints(
            budget=20,
            implementation_capacity=4,
            maximum_risk=4,
            objective="MAXIMIZE_THROUGHPUT",
            evaluation_runs=3,
        ),
        duration_hours=1,
        seed=2,
    )
    assert result["decision"] == "TRANSFORM"
    assert result["best"]["interventions"]
    assert result["best"]["score"] > 0


def test_baseline_api_accepts_48h_and_rejects_more_than_72h() -> None:
    with TestClient(main_mod.app) as client:
        accepted = client.get("/api/baseline?duration_hours=48&seed=7")
        rejected = client.get("/api/baseline?duration_hours=72.1&seed=7")
    assert accepted.status_code == 200
    assert rejected.status_code == 422
    assert "(0, 72]" in rejected.json()["detail"]
