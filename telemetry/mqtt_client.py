from __future__ import annotations

import json
import logging
import time
from typing import Any

from .ingestion import TelemetryIngestor

log = logging.getLogger(__name__)


class MQTTTelemetryConsumer:
    """MQTT adapter. paho-mqtt is loaded lazily so core simulation/API can run without a broker."""

    def __init__(self, ingestor: TelemetryIngestor, host: str, port: int = 1883, topic: str = "factory/line1/+/telemetry") -> None:
        self.ingestor = ingestor
        self.host = host
        self.port = port
        self.topic = topic
        self._client: Any = None

    def build_client(self):
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise RuntimeError("paho-mqtt is required for MQTT mode; install project dependencies") from exc
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        self._client = client
        return client

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        if int(reason_code) == 0:
            client.subscribe(self.topic, qos=1)
        else:
            log.error("MQTT connect failed: %s", reason_code)

    def _on_message(self, _client, _userdata, message) -> None:
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.ingestor.rejected_count += 1
            self.ingestor.errors.append({"type": "mqtt_decode", "error": str(exc)})
            return
        self.ingestor.ingest(payload)

    def run_forever(self) -> None:
        client = self.build_client()
        delay = 1.0
        while True:
            try:
                client.connect(self.host, self.port, keepalive=30)
                client.loop_forever(retry_first_connection=False)
                delay = 1.0
            except OSError as exc:
                log.warning("MQTT unavailable (%s); retrying in %.1fs", exc, delay)
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
