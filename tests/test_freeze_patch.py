from __future__ import annotations

import json
from pathlib import Path

import joblib
from fastapi.testclient import TestClient

from backend.app import main as main_mod
from scripts import train_ml


def _scenario(name: str, *, seed: int = 7, duration_hours: float = 1.0) -> dict:
    return {
        "name": name,
        "interventions": [],
        "duration_hours": duration_hours,
        "seed": seed,
        "parameters": {},
    }


def _sensitivity_payload(a: dict, b: dict) -> dict:
    return {"scenarios": [a, b]}


def test_sensitivity_accepts_same_seed_and_horizon() -> None:
    payload = _sensitivity_payload(_scenario("a"), _scenario("b"))
    with TestClient(main_mod.app) as client:
        response = client.post("/api/sensitivity", headers={"X-Admin-Token": "test-token"}, json=payload)
    assert response.status_code == 200
    assert response.json()["cases_tested"] > 0


def test_sensitivity_rejects_different_seed() -> None:
    payload = _sensitivity_payload(_scenario("a", seed=7), _scenario("b", seed=8))
    with TestClient(main_mod.app) as client:
        response = client.post("/api/sensitivity", headers={"X-Admin-Token": "test-token"}, json=payload)
    assert response.status_code == 422
    assert "same seed" in response.json()["detail"]
    assert "b" in response.json()["detail"]


def test_sensitivity_rejects_different_horizon() -> None:
    payload = _sensitivity_payload(_scenario("a", duration_hours=1), _scenario("b", duration_hours=2))
    with TestClient(main_mod.app) as client:
        response = client.post("/api/sensitivity", headers={"X-Admin-Token": "test-token"}, json=payload)
    assert response.status_code == 422
    assert "same duration_hours" in response.json()["detail"]
    assert "b" in response.json()["detail"]


def _write_valid_model(path: Path) -> None:
    joblib.dump(
        {
            "model": "test-model-object",
            "features": ["vibration_mm_s"],
            "threshold": 0.5,
            "model_version": "test-model",
        },
        path,
    )


def _valid_metadata() -> dict:
    return {
        "precision": 0.1,
        "recall": 0.2,
        "f1": 0.13,
        "roc_auc": 0.7,
        "pr_auc": 0.2,
        "features": ["vibration_mm_s"],
        "model_version": "test-model",
    }


def test_train_if_missing_skips_complete_artifacts(monkeypatch, tmp_path: Path) -> None:
    _write_valid_model(tmp_path / train_ml.MODEL_NAME)
    (tmp_path / train_ml.EVALUATION_NAME).write_text(json.dumps(_valid_metadata()), encoding="utf-8")
    called = False

    def fail_train(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("training should not run when complete artifacts exist")

    monkeypatch.setattr(train_ml, "train_and_evaluate", fail_train)
    result = train_ml.ensure_ml_artifacts(tmp_path, if_missing=True)
    assert result["status"] == "skipped_existing"
    assert called is False


def test_train_if_missing_trains_when_required_artifact_is_missing(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / train_ml.EVALUATION_NAME).write_text(json.dumps(_valid_metadata()), encoding="utf-8")
    calls: list[tuple[Path, int, float]] = []

    def fake_train(output_dir, runs: int, duration_hours: float):
        out = Path(output_dir)
        calls.append((out, runs, duration_hours))
        out.mkdir(parents=True, exist_ok=True)
        _write_valid_model(out / train_ml.MODEL_NAME)
        (out / train_ml.EVALUATION_NAME).write_text(json.dumps(_valid_metadata()), encoding="utf-8")
        return _valid_metadata()

    monkeypatch.setattr(train_ml, "train_and_evaluate", fake_train)
    result = train_ml.ensure_ml_artifacts(tmp_path, if_missing=True, runs=3, duration_hours=2.0)
    assert result["status"] == "trained"
    assert calls == [(tmp_path, 3, 2.0)]
    assert train_ml.artifacts_ready(tmp_path)


def test_train_if_missing_retrains_when_evaluation_metadata_is_incomplete(monkeypatch, tmp_path: Path) -> None:
    _write_valid_model(tmp_path / train_ml.MODEL_NAME)
    (tmp_path / train_ml.EVALUATION_NAME).write_text(json.dumps({"model_version": "incomplete"}), encoding="utf-8")
    calls = 0

    def fake_train(output_dir, runs: int, duration_hours: float):
        nonlocal calls
        calls += 1
        out = Path(output_dir)
        (out / train_ml.EVALUATION_NAME).write_text(json.dumps(_valid_metadata()), encoding="utf-8")
        return _valid_metadata()

    monkeypatch.setattr(train_ml, "train_and_evaluate", fake_train)
    result = train_ml.ensure_ml_artifacts(tmp_path, if_missing=True)
    assert result["status"] == "trained"
    assert calls == 1


def test_force_retrains_even_when_artifacts_exist(monkeypatch, tmp_path: Path) -> None:
    _write_valid_model(tmp_path / train_ml.MODEL_NAME)
    (tmp_path / train_ml.EVALUATION_NAME).write_text(json.dumps(_valid_metadata()), encoding="utf-8")
    calls = 0

    def fake_train(output_dir, runs: int, duration_hours: float):
        nonlocal calls
        calls += 1
        return _valid_metadata()

    monkeypatch.setattr(train_ml, "train_and_evaluate", fake_train)
    result = train_ml.ensure_ml_artifacts(tmp_path, if_missing=True, force=True)
    assert result["status"] == "trained"
    assert calls == 1
