from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from pydantic import ValidationError

from digital_twin import TwinStore

from .schemas import TelemetryEvent


@dataclass(slots=True)
class IngestionResult:
    accepted: bool
    duplicate: bool = False
    error: str | None = None
    late: bool = False


class TelemetryIngestor:
    def __init__(
        self,
        twin_store: TwinStore | None = None,
        *,
        dedupe_capacity: int = 10000,
        error_capacity: int = 500,
        predictor: Callable[[TelemetryEvent], dict[str, Any]] | None = None,
    ) -> None:
        self.twin_store = twin_store or TwinStore()
        self.predictor = predictor
        self._seen_order: deque[str] = deque(maxlen=dedupe_capacity)
        self._seen: set[str] = set()
        self.errors: deque[dict[str, Any]] = deque(maxlen=error_capacity)
        self.accepted_count = 0
        self.duplicate_count = 0
        self.rejected_count = 0
        self.late_count = 0
        self._lock = RLock()

    def ingest(self, payload: dict[str, Any], *, skip_memory_dedupe: bool = False) -> IngestionResult:
        try:
            event = TelemetryEvent.model_validate(payload)
        except ValidationError as exc:
            self.rejected_count += 1
            self.errors.append({"type": "validation", "error": str(exc), "payload": payload})
            return IngestionResult(False, error="invalid telemetry payload")

        with self._lock:
            if not skip_memory_dedupe and event.event_id in self._seen:
                self.duplicate_count += 1
                return IngestionResult(False, duplicate=True)
            if len(self._seen_order) == self._seen_order.maxlen and self._seen_order:
                self._seen.discard(self._seen_order.popleft())
            self._seen_order.append(event.event_id)
            self._seen.add(event.event_id)

            previous = self.twin_store.get(event.machine_id)
            late = bool(previous and previous.get("updated_at") and event.timestamp < previous["updated_at"])

            # Late telemetry remains historically valid, but it must not enter the
            # current-state ML rolling window or change the current health result.
            health = None
            if self.predictor and not late:
                try:
                    health = self.predictor(event)
                except Exception as exc:
                    self.errors.append({"type": "inference", "error": str(exc), "event_id": event.event_id})

            self.twin_store.update(event, health, datetime.now(UTC))
            self.accepted_count += 1
            if late:
                self.late_count += 1

        return IngestionResult(True, late=late)

    def stats(self) -> dict[str, int]:
        return {
            "accepted": self.accepted_count,
            "duplicates": self.duplicate_count,
            "rejected": self.rejected_count,
            "late": self.late_count,
            "dedupe_cache": len(self._seen),
        }
