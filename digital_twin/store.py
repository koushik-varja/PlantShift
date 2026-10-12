from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from threading import RLock
from typing import Any


@dataclass(slots=True)
class TwinState:
    machine_id: str
    state: str = "OFFLINE"
    health_score: float = 100.0
    health_state: str = "UNKNOWN"
    failure_probability: float | None = None
    model_version: str | None = None
    warning_reason: str | None = None
    feature_timestamp: str | None = None
    health_features: dict[str, float | int] | None = None
    current_production_job: str | None = None
    latest_telemetry: dict[str, Any] | None = None
    recent_telemetry: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=120))
    degradation: float | None = None
    maintenance_status: str = "none"
    quality_status: str = "unknown"
    updated_at: datetime | None = None
    ingest_updated_at: datetime | None = None
    event_count: int = 0
    late_event_count: int = 0

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data["recent_telemetry"] = list(self.recent_telemetry)
        return data


class TwinStore:
    def __init__(self) -> None:
        self._twins: dict[str, TwinState] = {}
        self._lock = RLock()

    def update(
        self,
        event: Any,
        health: dict[str, Any] | None = None,
        ingest_time: datetime | None = None,
    ) -> TwinState:
        with self._lock:
            twin = self._twins.setdefault(
                event.machine_id,
                TwinState(machine_id=event.machine_id),
            )
            payload = event.model_dump(mode="json")
            twin.recent_telemetry.append(payload)
            twin.event_count += 1
            if twin.updated_at is not None and event.timestamp < twin.updated_at:
                twin.late_event_count += 1
                return twin

            twin.state = event.state
            twin.degradation = float(event.wear) if event.wear is not None else twin.degradation
            twin.current_production_job = event.cycle_id
            twin.latest_telemetry = payload
            twin.maintenance_status = "active" if event.state == "MAINTENANCE" else "none"
            twin.updated_at = event.timestamp
            twin.ingest_updated_at = ingest_time

            if health:
                twin.health_state = str(health["health_state"])
                twin.failure_probability = float(health["failure_probability"])
                twin.model_version = str(health["model_version"])
                twin.warning_reason = str(health["warning_reason"])
                twin.feature_timestamp = str(health["feature_timestamp"])
                twin.health_features = dict(health["features"])
                twin.health_score = round(
                    100.0 * (1.0 - twin.failure_probability),
                    2,
                )
                twin.quality_status = "watch" if twin.failure_probability >= 0.5 else "nominal"
            elif event.wear is not None:
                twin.health_score = round(
                    max(0.0, 100.0 * (1.0 - min(1.0, event.wear))),
                    2,
                )
                twin.quality_status = "watch" if event.wear >= 0.65 else "nominal"
            return twin

    def get(self, machine_id: str) -> dict[str, Any] | None:
        with self._lock:
            twin = self._twins.get(machine_id)
            return twin.public() if twin else None

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._twins[key].public() for key in sorted(self._twins)]
