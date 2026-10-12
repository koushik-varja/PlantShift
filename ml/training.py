from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from factory_simulator import FactorySimulator, baseline_config

# Only observable/deployable telemetry-derived features. Simulator wear is ground truth only.
FEATURES = [
    "vibration_mm_s",
    "temperature_c",
    "load",
    "rpm",
    "energy_kw",
    "cycle_count",
    "vibration_roll3",
    "vibration_std3",
    "temp_roll3",
    "temp_trend3",
    "energy_roll3",
]


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    required = {
        "run_id",
        "machine_id",
        "timestamp",
        "vibration_mm_s",
        "temperature_c",
        "load",
        "rpm",
        "energy_kw",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"missing telemetry feature columns: {sorted(missing)}")

    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
    out = out.sort_values(["run_id", "machine_id", "timestamp"]).reset_index(drop=True)
    keys = ["run_id", "machine_id"]
    grouped = out.groupby(keys, group_keys=False, sort=False)
    out["cycle_count"] = grouped.cumcount() + 1
    out["vibration_roll3"] = grouped["vibration_mm_s"].rolling(3, min_periods=1).mean().reset_index(level=keys, drop=True)
    out["vibration_std3"] = grouped["vibration_mm_s"].rolling(3, min_periods=1).std(ddof=0).reset_index(level=keys, drop=True).fillna(0.0)
    out["temp_roll3"] = grouped["temperature_c"].rolling(3, min_periods=1).mean().reset_index(level=keys, drop=True)
    out["temp_trend3"] = grouped["temperature_c"].diff(3).fillna(0.0)
    out["energy_roll3"] = grouped["energy_kw"].rolling(3, min_periods=1).mean().reset_index(level=keys, drop=True)
    return out


def build_training_frame(runs: int = 18, duration_hours: float = 12.0) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for index in range(runs):
        simulator = FactorySimulator(
            baseline_config(duration_hours),
            seed=500 + index,
            demand_seed=9001 + index,
            run_id=f"ml-{index}",
        )
        simulator.run()
        rows.extend(simulator.telemetry)

    if not rows:
        raise RuntimeError("simulator produced no telemetry")

    df = engineer_features(pd.DataFrame(rows))
    # Synthetic ground truth is used only to create labels, never as a model feature.
    df["future_failure"] = 0
    for _, indices in df.groupby(["run_id", "machine_id"], sort=False).groups.items():
        positions = list(indices)
        failures = set(df.loc[positions][df.loc[positions, "failure_event"]].index)
        for position_index, row_index in enumerate(positions):
            if any(candidate in failures for candidate in positions[position_index + 1 : position_index + 6]):
                df.at[row_index, "future_failure"] = 1
    return df


def split_training_frame_by_run(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, list[str]]]:
    """Chronologically split whole synthetic runs into approximately 60/10/30 partitions."""
    if "run_id" not in df.columns or "timestamp" not in df.columns:
        raise ValueError("training frame must contain run_id and timestamp")

    work = df.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    ordered_runs = list(work.groupby("run_id")["timestamp"].min().sort_values(kind="stable").index)
    n_runs = len(ordered_runs)
    if n_runs < 3:
        raise RuntimeError("at least three complete simulation runs are required for train/validation/test splitting")

    train_count = max(1, int(round(n_runs * 0.60)))
    validation_count = max(1, int(round(n_runs * 0.10)))
    if train_count + validation_count >= n_runs:
        train_count = max(1, n_runs - validation_count - 1)
    test_count = n_runs - train_count - validation_count
    if test_count < 1:
        raise RuntimeError("unable to allocate at least one complete run to each split")

    train_run_ids = ordered_runs[:train_count]
    validation_run_ids = ordered_runs[train_count : train_count + validation_count]
    test_run_ids = ordered_runs[train_count + validation_count :]
    run_sets = [set(train_run_ids), set(validation_run_ids), set(test_run_ids)]
    if run_sets[0] & run_sets[1] or run_sets[0] & run_sets[2] or run_sets[1] & run_sets[2]:
        raise RuntimeError("run_id overlap detected across ML partitions")

    def subset(run_ids: list[str]) -> pd.DataFrame:
        return work[work["run_id"].isin(run_ids)].sort_values(["timestamp", "run_id", "machine_id"]).reset_index(drop=True)

    return (
        subset(train_run_ids),
        subset(validation_run_ids),
        subset(test_run_ids),
        {
            "train": train_run_ids,
            "validation": validation_run_ids,
            "test": test_run_ids,
        },
    )


def train_and_evaluate(
    output_dir: str | Path,
    runs: int = 18,
    duration_hours: float = 12.0,
) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    df = build_training_frame(runs=runs, duration_hours=duration_hours)
    train, validation, test, split_runs = split_training_frame_by_run(df)

    if train["future_failure"].nunique() < 2 or validation["future_failure"].nunique() < 2 or test["future_failure"].nunique() < 2:
        raise RuntimeError("insufficient positive/negative failure labels; increase runs or duration")

    model = RandomForestClassifier(
        n_estimators=160,
        max_depth=7,
        min_samples_leaf=3,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(train[FEATURES], train["future_failure"])

    validation_prob = model.predict_proba(validation[FEATURES])[:, 1]
    thresholds = np.linspace(0.10, 0.85, 76)
    threshold = float(
        max(
            thresholds,
            key=lambda candidate: f1_score(
                validation["future_failure"],
                (validation_prob >= candidate).astype(int),
                zero_division=0,
            ),
        )
    )

    probability = model.predict_proba(test[FEATURES])[:, 1]
    prediction = (probability >= threshold).astype(int)
    feature_importance_pairs: list[tuple[str, float]] = [
        (name, float(score))
        for name, score in zip(
            FEATURES,
            model.feature_importances_,
            strict=True,
        )
    ]
    feature_importance_pairs.sort(key=lambda item: item[1], reverse=True)
    feature_importance = [{"feature": name, "importance": importance} for name, importance in feature_importance_pairs]
    metrics = {
        "precision": float(precision_score(test["future_failure"], prediction, zero_division=0)),
        "recall": float(recall_score(test["future_failure"], prediction, zero_division=0)),
        "f1": float(f1_score(test["future_failure"], prediction, zero_division=0)),
        "roc_auc": float(roc_auc_score(test["future_failure"], probability)),
        "pr_auc": float(average_precision_score(test["future_failure"], probability)),
        "confusion_matrix": confusion_matrix(test["future_failure"], prediction).tolist(),
        "feature_importance": feature_importance,
        "features": FEATURES,
        "latent_wear_used_as_feature": False,
        "train_rows": int(len(train)),
        "validation_rows": int(len(validation)),
        "test_rows": int(len(test)),
        "decision_threshold": threshold,
        "positive_rate_train": float(train["future_failure"].mean()),
        "positive_rate_test": float(test["future_failure"].mean()),
        "split": ("whole-run chronological split, approximately 60/10/30; threshold chosen on validation only"),
        "train_runs": split_runs["train"],
        "validation_runs": split_runs["validation"],
        "test_runs": split_runs["test"],
        "run_overlap": False,
        "label": ("failure within next five same-run/same-machine telemetry events; synthetic ground truth"),
        "synthetic_data": True,
        "model_version": "failure-risk-rf-v2-observable",
    }
    joblib.dump(
        {
            "model": model,
            "features": FEATURES,
            "threshold": threshold,
            "model_version": metrics["model_version"],
        },
        out / "failure_risk.joblib",
    )
    (out / "evaluation.json").write_text(
        json.dumps(metrics, indent=2),
        encoding="utf-8",
    )
    return metrics


def load_model(path: str | Path) -> Any:
    return joblib.load(path)
