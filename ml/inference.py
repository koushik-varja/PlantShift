from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

import joblib
import numpy as np
import pandas as pd


class FailureRiskService:
    """Loads one model once and maintains bounded per-machine observable feature history."""

    def __init__(self, model_path: str | Path) -> None:
        bundle = joblib.load(model_path)
        self.model = bundle["model"]
        self.features: list[str] = list(bundle["features"])
        self.threshold = float(bundle.get("threshold", 0.5))
        self.model_version = str(bundle.get("model_version", "unknown"))
        self._history: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=3))
        self._counts: dict[str, int] = defaultdict(int)
        self._lock = RLock()

    def predict(self, event: Any) -> dict[str, Any]:
        row = event.model_dump(mode="python") if hasattr(event, "model_dump") else dict(event)
        key = str(row["machine_id"])
        with self._lock:
            h = self._history[key]
            h.append(row)
            self._counts[key] += 1
            values = list(h)
            temps = [float(x["temperature_c"]) for x in values]
            vibrations = [float(x["vibration_mm_s"]) for x in values]
            energies = [float(x["energy_kw"]) for x in values]
            feat = {
                "vibration_mm_s": float(row["vibration_mm_s"]),
                "temperature_c": float(row["temperature_c"]),
                "load": float(row["load"]),
                "rpm": float(row["rpm"]),
                "energy_kw": float(row["energy_kw"]),
                "cycle_count": int(row.get("production_context", {}).get("cycle_count") or self._counts[key]),
                "vibration_roll3": float(np.mean(vibrations)),
                "vibration_std3": float(np.std(vibrations)),
                "temp_roll3": float(np.mean(temps)),
                "temp_trend3": float(temps[-1] - temps[0]) if len(temps) >= 3 else 0.0,
                "energy_roll3": float(np.mean(energies)),
            }
            frame = pd.DataFrame([{name: feat[name] for name in self.features}], columns=self.features)
            probability = float(self.model.predict_proba(frame)[0, 1])
        if probability >= self.threshold:
            state, reason = "HIGH_RISK", "failure-risk probability exceeds the validated model decision threshold"
        elif probability >= max(0.20, self.threshold * 0.40):
            state, reason = "WATCH", "failure-risk probability is elevated but below the validated decision threshold"
        else:
            state, reason = "NOMINAL", "failure-risk probability remains below the operational watch band"
        ts = row["timestamp"]
        if isinstance(ts, datetime):
            ts = ts.isoformat()
        return {
            "health_state": state,
            "failure_probability": round(probability, 6),
            "model_version": self.model_version,
            "feature_timestamp": str(ts),
            "features": feat,
            "warning_reason": reason,
        }
