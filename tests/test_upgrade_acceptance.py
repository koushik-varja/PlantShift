from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import main as main_mod
from backend.app.db import Base, ProcessedEvent, SessionLocal, engine
from backend.app.services import maintenance_window_comparison
from edge_adapters.legacy_adapter import LegacyEdgeAdapter
from factory_simulator import FactorySimulator, baseline_config
from ml import FEATURES, FailureRiskService, build_training_frame
from optimizer import (
    BusinessAssumptions,
    PortfolioConstraints,
    build_roadmap,
    business_value,
    optimize_portfolio,
)
from scenario_engine import Scenario, run_scenario
from scripts import mqtt_bridge
from telemetry import TelemetryIngestor


def test_real_maintenance_windows_change_mechanics():
    rows = maintenance_window_comparison("B", 24, 17, 30)
    by = {row["option"]: row for row in rows}
    assert by["MAINTENANCE_NOW"]["planned_downtime_min"] == 30
    assert by["LOW_DEMAND_WINDOW"]["planned_downtime_min"] == 30
    assert by["RUN_TO_FAILURE"]["planned_downtime_min"] == 0
    assert len({row["throughput_units"] for row in rows}) > 1


def test_ml_has_no_latent_wear_and_run_boundaries_reset():
    assert "wear" not in FEATURES
    df = build_training_frame(runs=2, duration_hours=2)
    starts = df.sort_values(["run_id", "machine_id", "timestamp"]).groupby(["run_id", "machine_id"]).head(1)
    assert (starts["vibration_roll3"].round(8) == starts["vibration_mm_s"].round(8)).all()
    assert (starts["temp_trend3"] == 0).all()


def test_runtime_inference_returns_real_model_output():
    model = Path("ml/artifacts/failure_risk.joblib")
    service = FailureRiskService(model)
    simulator = FactorySimulator(baseline_config(1), seed=8)
    simulator.run()
    event = simulator.telemetry[0]

    result = service.predict(event)

    assert 0 <= result["failure_probability"] <= 1
    assert result["model_version"]
    assert "wear" not in result["features"]


def test_optimizer_uses_paired_seeds_constraints_and_energy_objective():
    constraints = PortfolioConstraints(
        budget=20,
        implementation_capacity=4,
        maximum_risk=4,
        objective="MINIMIZE_ENERGY",
        evaluation_runs=3,
    )
    result = optimize_portfolio(constraints, duration_hours=1, seed=4)

    assert result["best"] is not None and result["best"]["cost"] <= 20
    assert len(result["best"]["paired_seeds"]) == 3
    assert {"median", "p10", "p90"} <= set(result["best"]["robust_deltas"]["energy"])


def test_energy_intervention_changes_energy_per_unit():
    baseline = run_scenario(Scenario("b", []), duration_hours=2, seed=7)
    efficient = run_scenario(
        Scenario("e", ["energy_efficiency"]),
        duration_hours=2,
        seed=7,
    )

    assert efficient["energy_per_finished_unit_kwh"] < baseline["energy_per_finished_unit_kwh"]


def test_brownfield_normalization_two_schemas():
    adapter = LegacyEdgeAdapter()
    legacy_a = adapter.normalize(
        {
            "MACHINE": "A",
            "TEMP_F": 171.4,
            "VIB_IN_S": 0.11,
            "MOTOR_RPM": 1800,
            "LOAD_PCT": 80,
            "KW": 6.2,
        }
    )
    legacy_b = adapter.normalize(
        {
            "assetId": "B",
            "temperature_c": 76.3,
            "vibration_mm_s": 2.9,
            "rpm": 1760,
            "load": 0.7,
            "power_kw": 8.1,
        }
    )

    assert legacy_a["machine_id"] == "machineA"
    assert abs(legacy_a["temperature_c"] - 77.4444) < 0.01
    assert legacy_b["machine_id"] == "machineB"
    assert legacy_b["vibration_mm_s"] == 2.9
    assert legacy_a["wear"] is None and legacy_b["wear"] is None


def test_late_event_is_historical_but_twin_does_not_regress():
    simulator = FactorySimulator(baseline_config(1), seed=9)
    simulator.run()
    events = [event for event in simulator.telemetry if event["machine_id"] == "machineA"][:2]
    old, new = sorted(events, key=lambda event: event["timestamp"])
    ingestor = TelemetryIngestor()

    assert ingestor.ingest(new).accepted
    latest_before = ingestor.twin_store.get("machineA")["latest_telemetry"]["event_id"]
    result = ingestor.ingest(old)

    assert result.accepted and result.late
    twin = ingestor.twin_store.get("machineA")
    assert twin["latest_telemetry"]["event_id"] == latest_before
    assert twin["late_event_count"] == 1


def test_bridge_bounded_retry_and_dlq(tmp_path, monkeypatch):
    monkeypatch.setattr(mqtt_bridge, "DLQ_PATH", tmp_path / "dlq.jsonl")
    mqtt_bridge.metrics.retry_count = 0
    mqtt_bridge.metrics.dead_letter_count = 0
    mqtt_bridge.metrics.delivery_success = 0
    attempts = []

    def fail(_raw):
        attempts.append(1)
        raise OSError("down")

    assert (
        mqtt_bridge.deliver_with_retries(
            b"{}",
            post_fn=fail,
            sleep_fn=lambda _delay: None,
            max_retries=2,
        )
        is False
    )
    assert len(attempts) == 3
    assert mqtt_bridge.metrics.retry_count == 2
    assert mqtt_bridge.metrics.dead_letter_count == 1
    assert (tmp_path / "dlq.jsonl").exists()


def test_cost_override_changes_reported_illustrative_cost():
    result = run_scenario(
        Scenario(
            "x",
            ["energy_efficiency"],
            costs={"energy_efficiency": 3.5},
        ),
        duration_hours=1,
        seed=1,
    )
    assert result["transformation_cost"] == 3.5


def test_persistent_duplicate_survives_ingestor_reset():
    Base.metadata.create_all(bind=engine)
    simulator = FactorySimulator(baseline_config(1), seed=121)
    simulator.run()
    event = simulator.telemetry[0]

    with TestClient(main_mod.app) as client:
        first = client.post("/api/telemetry", json=event)
        assert first.status_code == 200

        main_mod.ingestor = TelemetryIngestor(
            main_mod.twins,
            predictor=main_mod.risk_service.predict if main_mod.risk_service else None,
        )
        second = client.post("/api/telemetry", json=event)
        assert second.status_code == 200
        assert second.json()["duplicate"] is True

    with SessionLocal() as db:
        count = db.query(ProcessedEvent).filter(ProcessedEvent.event_id == event["event_id"]).count()
        assert count == 1


def test_batch_endpoint_one_transaction_semantics_and_duplicates():
    simulator = FactorySimulator(baseline_config(1), seed=122)
    simulator.run()
    events = simulator.telemetry[:4]

    with TestClient(main_mod.app) as client:
        response = client.post("/api/telemetry/batch", json=events + [events[0]])
        assert response.status_code == 200
        body = response.json()
        assert body["accepted"] == 4 and body["duplicates"] == 1


def test_invalid_typed_intervention_parameter_rejected():
    payload = {
        "name": "bad",
        "interventions": ["quality_assist"],
        "duration_hours": 1,
        "seed": 1,
        "parameters": {"inspection_accuracy": 1.5},
    }
    with TestClient(main_mod.app) as client:
        response = client.post(
            "/api/scenarios/run",
            headers={"X-Admin-Token": "test-token"},
            json=payload,
        )
        assert response.status_code == 422


def test_degrading_observable_telemetry_changes_runtime_twin_health():
    model = Path("ml/artifacts/failure_risk.joblib")
    service = FailureRiskService(model)
    ingestor = TelemetryIngestor(predictor=service.predict)
    simulator = FactorySimulator(baseline_config(12), seed=777)
    simulator.run()
    events = [event for event in simulator.telemetry if event["machine_id"] == "machineB" and not event["failure_event"]]
    low = events[:3]
    high = max(events, key=lambda event: event["wear"])

    for event in low:
        ingestor.ingest(event)
    low_twin = ingestor.twin_store.get("machineB")

    high_index = events.index(high)
    for event in events[3 : high_index + 1]:
        ingestor.ingest(event)
    high_twin = ingestor.twin_store.get("machineB")

    assert high_twin["failure_probability"] > low_twin["failure_probability"]
    assert high_twin["health_score"] < low_twin["health_score"]
    assert high_twin["health_state"] in {"WATCH", "HIGH_RISK"}


def test_optimizer_objective_switching_changes_selected_portfolio():
    energy = optimize_portfolio(
        PortfolioConstraints(
            budget=20,
            implementation_capacity=4,
            maximum_risk=4,
            objective="MINIMIZE_ENERGY",
            evaluation_runs=3,
        ),
        duration_hours=1,
        seed=4,
    )
    throughput = optimize_portfolio(
        PortfolioConstraints(
            budget=20,
            implementation_capacity=4,
            maximum_risk=4,
            objective="MAXIMIZE_THROUGHPUT",
            evaluation_runs=3,
        ),
        duration_hours=1,
        seed=4,
    )

    assert energy["best"]["interventions"] != throughput["best"]["interventions"]


def test_optimizer_budget_zero_returns_explicit_no_action_baseline():
    result = optimize_portfolio(
        PortfolioConstraints(
            budget=0,
            implementation_capacity=1,
            maximum_risk=0,
            objective="MAXIMIZE_THROUGHPUT",
            evaluation_runs=3,
        ),
        duration_hours=1,
        seed=4,
    )
    assert result["decision"] == "NO_ACTION"
    assert result["best"]["interventions"] == []
    assert result["evaluated_feasible_combinations"] == 0


def test_business_value_accounts_for_energy_cost():
    baseline = run_scenario(Scenario("b", []), duration_hours=2, seed=7)
    efficient = run_scenario(
        Scenario("e", ["energy_efficiency"]),
        duration_hours=2,
        seed=7,
    )
    cheap = business_value(
        baseline,
        efficient,
        BusinessAssumptions(energy_cost_per_kwh=0.0),
    )
    costly = business_value(
        baseline,
        efficient,
        BusinessAssumptions(energy_cost_per_kwh=2.0),
    )

    assert costly["estimated_financial_effect"] > cheap["estimated_financial_effect"]


def test_roadmap_respects_wave_effort_without_inventing_dependencies():
    phases = build_roadmap(
        ["optimized_scheduling", "energy_efficiency"],
        max_effort_per_phase=2,
    )
    assert len(phases) == 2
    assert {intervention for phase in phases for intervention in phase["interventions"]} == {"optimized_scheduling", "energy_efficiency"}


def test_roadmap_rejects_missing_real_prerequisite():
    with pytest.raises(ValueError):
        build_roadmap(["condition_maintenance"])
