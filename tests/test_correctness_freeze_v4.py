from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import joblib
import pytest
from fastapi.testclient import TestClient

from backend.app import main as main_mod
from backend.app.db import SessionLocal, TelemetryRecord
from backend.app.services import maintenance_window_comparison
from digital_twin import TwinStore
from factory_simulator import FactorySimulator, baseline_config
from ml import build_training_frame, split_training_frame_by_run
from scenario_engine import Scenario, run_scenario
from scripts import train_ml
from telemetry import TelemetryIngestor


def _sample_event(seed: int = 321) -> dict:
    sim = FactorySimulator(baseline_config(1), seed=seed)
    sim.run()
    return deepcopy(sim.telemetry[0])


def test_same_batch_duplicate_first_event_wins_db_and_twin(monkeypatch: pytest.MonkeyPatch) -> None:
    fresh_twins = TwinStore()
    monkeypatch.setattr(main_mod, "twins", fresh_twins)
    monkeypatch.setattr(main_mod, "ingestor", TelemetryIngestor(fresh_twins))

    first = _sample_event()
    first.update(event_id="same-batch-first-wins-001", machine_id="machineA", stage="A", temperature_c=51.25)
    duplicate = deepcopy(first)
    duplicate.update(machine_id="machineD", stage="D", temperature_c=88.75)

    with TestClient(main_mod.app) as client:
        response = client.post("/api/telemetry/batch", json=[first, duplicate])
    assert response.status_code == 200
    assert response.json()["accepted"] == 1
    assert response.json()["duplicates"] == 1

    with SessionLocal() as db:
        row = db.query(TelemetryRecord).filter(TelemetryRecord.event_id == first["event_id"]).one()
        assert row.machine_id == "machineA"
        assert row.payload["machine_id"] == "machineA"
        assert row.payload["temperature_c"] == pytest.approx(51.25)

    twin_a = fresh_twins.get("machineA")
    assert twin_a is not None
    assert twin_a["event_count"] == 1
    assert twin_a["latest_telemetry"]["temperature_c"] == pytest.approx(51.25)
    assert fresh_twins.get("machineD") is None


def test_same_batch_duplicate_same_machine_cannot_overwrite_first_value(monkeypatch: pytest.MonkeyPatch) -> None:
    fresh_twins = TwinStore()
    monkeypatch.setattr(main_mod, "twins", fresh_twins)
    monkeypatch.setattr(main_mod, "ingestor", TelemetryIngestor(fresh_twins))

    first = _sample_event(322)
    first.update(event_id="same-batch-first-wins-002", machine_id="machineA", stage="A", temperature_c=49.0)
    duplicate = deepcopy(first)
    duplicate["temperature_c"] = 93.0

    with TestClient(main_mod.app) as client:
        response = client.post("/api/telemetry/batch", json=[first, duplicate])
    assert response.status_code == 200
    assert response.json()["accepted"] == 1
    assert response.json()["duplicates"] == 1
    assert fresh_twins.get("machineA")["latest_telemetry"]["temperature_c"] == pytest.approx(49.0)


def test_ml_split_keeps_complete_run_ids_disjoint() -> None:
    frame = build_training_frame(runs=6, duration_hours=3)
    train, validation, test, split_runs = split_training_frame_by_run(frame)
    train_ids, validation_ids, test_ids = map(set, (split_runs["train"], split_runs["validation"], split_runs["test"]))
    assert train_ids.isdisjoint(validation_ids)
    assert train_ids.isdisjoint(test_ids)
    assert validation_ids.isdisjoint(test_ids)
    assert set(train["run_id"].unique()) == train_ids
    assert set(validation["run_id"].unique()) == validation_ids
    assert set(test["run_id"].unique()) == test_ids
    assert train_ids | validation_ids | test_ids == set(frame["run_id"].unique())


def test_cbm_decision_uses_observable_history_not_latent_wear() -> None:
    sim = FactorySimulator(baseline_config(1), seed=17)
    sim.config.cbm_enabled = True
    sim.config.cbm_threshold = 0.62
    server = sim.servers["B"][0]
    cfg = sim.config.machines["B"]

    healthy = {
        "vibration_mm_s": 1.15 + 0.45 * 0.85,
        "temperature_c": 42.0 + 8.0 * 0.85,
        "load": 0.85,
        "rpm": float(cfg.nominal_rpm),
        "energy_kw": cfg.base_kw * (0.25 + 0.65 * 0.85),
    }
    server.wear = 1.0
    for _ in range(3):
        sim._remember_observable_condition("B", server, healthy)
    assert sim._should_trigger_condition_maintenance("B", server) is False

    server.condition_history.clear()
    server.wear = 0.05
    unhealthy = {
        "vibration_mm_s": 5.0,
        "temperature_c": 76.0,
        "load": 1.0,
        "rpm": 1220.0,
        "energy_kw": 10.6,
    }
    for _ in range(3):
        sim._remember_observable_condition("B", server, unhealthy)
    assert sim._should_trigger_condition_maintenance("B", server) is True


def test_maintenance_policy_comparison_uses_common_iot_visibility(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[Scenario, float, int, int]] = []

    def fake_run(scenario: Scenario, *, duration_hours: float, seed: int, demand_seed: int, **kwargs):
        captured.append((scenario, duration_hours, seed, demand_seed))
        return {
            "throughput_units": 1,
            "planned_downtime_min": 0,
            "unplanned_downtime_min": 0,
            "late_orders": 0,
            "average_queue_lengths": {"B": 0},
            "machines": {},
            "energy_kwh": 1,
        }

    monkeypatch.setattr("backend.app.services.run_scenario", fake_run)
    maintenance_window_comparison("B", 24, 17, 30)
    assert len(captured) == 4
    assert all("iot_retrofit" in scenario.interventions for scenario, _, _, _ in captured)
    assert all(duration == 24 and seed == 17 and demand_seed == 2026 for _, duration, seed, demand_seed in captured)
    run_to_failure = next(s for s, _, _, _ in captured if s.name == "run_to_failure")
    assert run_to_failure.interventions == ["iot_retrofit"]


def test_condition_triggered_is_not_a_maintenance_window_api_strategy() -> None:
    payload = {
        "name": "invalid-condition-window",
        "interventions": ["iot_retrofit", "maintenance_window"],
        "duration_hours": 24,
        "seed": 7,
        "parameters": {"maintenance_strategy": "CONDITION_TRIGGERED"},
    }
    with TestClient(main_mod.app) as client:
        response = client.post("/api/scenarios/run", headers={"X-Admin-Token": "test-token"}, json=payload)
    assert response.status_code == 422


def test_run_to_failure_is_not_a_fake_maintenance_window_intervention() -> None:
    with pytest.raises(ValueError, match="RUN_TO_FAILURE is a comparison/baseline policy"):
        run_scenario(
            Scenario(
                "bad-run-to-failure",
                ["iot_retrofit", "maintenance_window"],
                parameters={"maintenance_strategy": "RUN_TO_FAILURE"},
            ),
            duration_hours=24,
            seed=7,
        )


def _valid_evaluation() -> dict:
    return {
        "precision": 0.1,
        "recall": 0.2,
        "f1": 0.13,
        "roc_auc": 0.7,
        "pr_auc": 0.2,
        "features": ["vibration_mm_s"],
        "model_version": "test-model",
    }


def test_corrupt_model_is_not_ready_and_if_missing_retrains(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / train_ml.MODEL_NAME).write_bytes(b"not-a-joblib-model")
    (tmp_path / train_ml.EVALUATION_NAME).write_text(__import__("json").dumps(_valid_evaluation()), encoding="utf-8")
    assert train_ml.artifacts_ready(tmp_path) is False

    calls = 0

    def fake_train(output_dir, runs: int, duration_hours: float):
        nonlocal calls
        calls += 1
        out = Path(output_dir)
        joblib.dump(
            {"model": "replacement", "features": ["vibration_mm_s"], "threshold": 0.5, "model_version": "test-model"},
            out / train_ml.MODEL_NAME,
        )
        (out / train_ml.EVALUATION_NAME).write_text(__import__("json").dumps(_valid_evaluation()), encoding="utf-8")
        return _valid_evaluation()

    monkeypatch.setattr(train_ml, "train_and_evaluate", fake_train)
    result = train_ml.ensure_ml_artifacts(tmp_path, if_missing=True)
    assert result["status"] == "trained"
    assert calls == 1
    assert train_ml.artifacts_ready(tmp_path) is True
