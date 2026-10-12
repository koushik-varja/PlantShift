from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

MACHINE_STAGE = {
    "A": "A",
    "B": "B",
    "C": "C",
    "D": "D",
    "machineA": "A",
    "machineB": "B",
    "machineC": "C",
    "machineD": "D",
}


def _machine_id(value: str) -> str:
    if value.startswith("machine"):
        return value
    normalized = value.upper()
    if normalized not in {"A", "B", "C", "D"}:
        raise ValueError("unknown machine identifier")
    return f"machine{normalized}"


def _base(machine: str, timestamp: Any = None) -> dict[str, Any]:
    machine_id = _machine_id(str(machine))
    stage = MACHINE_STAGE.get(machine_id, machine_id[-1].upper())
    return {
        "event_id": str(uuid4()),
        "run_id": "legacy-live",
        "machine_id": machine_id,
        "stage": stage,
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
        "sim_minute": 0.0,
        "state": "RUNNING",
        "cycle_id": None,
        "failure_event": False,
        "production_context": {"source": "legacy_edge_adapter"},
    }


class LegacyEdgeAdapter:
    """Brownfield normalizer supporting incompatible legacy schemas and unit conversion."""

    def __init__(self, broker_host: str = "localhost", broker_port: int = 1883) -> None:
        self.broker_host = broker_host
        self.broker_port = broker_port
        self._client = None

    def normalize(self, raw: dict[str, Any] | str) -> dict[str, Any]:
        if isinstance(raw, str):
            reader = csv.DictReader(io.StringIO(raw))
            rows = list(reader)
            if len(rows) != 1:
                raise ValueError("CSV payload must contain exactly one row")
            raw = rows[0]

        if "MACHINE" in raw:  # legacy imperial controller
            out = _base(str(raw["MACHINE"]), raw.get("TS"))
            out.update(
                {
                    "temperature_c": (float(raw["TEMP_F"]) - 32) * 5 / 9,
                    "vibration_mm_s": float(raw["VIB_IN_S"]) * 25.4,
                    "rpm": float(raw["MOTOR_RPM"]),
                    "load": float(raw.get("LOAD_PCT", 75)) / 100,
                    "energy_kw": float(raw.get("KW", 0)),
                }
            )
        elif "assetId" in raw:
            out = _base(str(raw["assetId"]), raw.get("timestamp"))
            out.update(
                {
                    "temperature_c": float(raw["temperature_c"]),
                    "vibration_mm_s": float(raw["vibration_mm_s"]),
                    "rpm": float(raw["rpm"]),
                    "load": float(raw.get("load", 0.75)),
                    "energy_kw": float(raw.get("power_kw", 0)),
                }
            )
        elif "machine" in raw:  # CSV/batch-style export
            out = _base(str(raw["machine"]), raw.get("timestamp"))
            out.update(
                {
                    "temperature_c": float(raw["temp_c"]),
                    "vibration_mm_s": float(raw["vibration"]),
                    "rpm": float(raw["rpm"]),
                    "load": float(raw.get("load", 0.75)),
                    "energy_kw": float(raw.get("kw", 0)),
                }
            )
        else:
            required = {
                "event_id",
                "run_id",
                "machine_id",
                "stage",
                "timestamp",
                "sim_minute",
                "state",
                "vibration_mm_s",
                "temperature_c",
                "load",
                "rpm",
                "energy_kw",
            }
            missing = required - raw.keys()
            if missing:
                raise ValueError(f"unrecognized legacy schema; missing canonical fields: {sorted(missing)}")
            out = dict(raw)

        out.setdefault("wear", None)
        out["temperature_c"] = round(float(out["temperature_c"]), 4)
        out["vibration_mm_s"] = round(float(out["vibration_mm_s"]), 4)
        if not 0 <= float(out["load"]) <= 2 or float(out["rpm"]) < 0 or float(out["energy_kw"]) < 0:
            raise ValueError("legacy payload contains invalid physical values")
        return out

    def connect(self) -> None:
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise RuntimeError("paho-mqtt is required") from exc

        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.connect(self.broker_host, self.broker_port, keepalive=30)
        self._client.loop_start()

    def publish(self, event: dict[str, Any] | str) -> None:
        if self._client is None:
            raise RuntimeError("adapter is not connected")
        payload = self.normalize(event)
        info = self._client.publish(
            f"factory/line1/{payload['machine_id']}/telemetry",
            json.dumps(payload),
            qos=1,
        )
        info.wait_for_publish(timeout=2)

    def close(self) -> None:
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
