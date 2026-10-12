from __future__ import annotations

import json
import logging
import os
import queue
import random
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request

try:
    import paho.mqtt.client as mqtt
except ImportError:  # unit tests can exercise delivery logic without MQTT installed
    mqtt = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("plantshift.mqtt_bridge")

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
BACKEND_URL = os.getenv("BACKEND_TELEMETRY_URL", "http://backend:8000/api/telemetry/batch")
TOPIC = os.getenv("MQTT_TOPIC", "factory/line1/+/telemetry")
BUFFER_SIZE = int(os.getenv("MQTT_BRIDGE_BUFFER", "1000"))
MAX_RETRIES = int(os.getenv("MQTT_BRIDGE_MAX_RETRIES", "4"))
BATCH_SIZE = int(os.getenv("MQTT_BRIDGE_BATCH_SIZE", "50"))
BATCH_FLUSH_MS = float(os.getenv("MQTT_BRIDGE_BATCH_FLUSH_MS", "50"))
DLQ_PATH = Path(os.getenv("MQTT_BRIDGE_DLQ", "benchmarks/results/mqtt_bridge_dlq.jsonl"))
METRICS_PORT = int(os.getenv("MQTT_BRIDGE_METRICS_PORT", "9102"))

if not 1 <= BATCH_SIZE <= 200:
    raise ValueError("MQTT_BRIDGE_BATCH_SIZE must be between 1 and 200")
if not 1 <= BATCH_FLUSH_MS <= 5000:
    raise ValueError("MQTT_BRIDGE_BATCH_FLUSH_MS must be between 1 and 5000 milliseconds")

messages: queue.Queue[bytes] = queue.Queue(maxsize=BUFFER_SIZE)


@dataclass(slots=True)
class BridgeMetrics:
    delivery_success: int = 0
    http_batch_deliveries: int = 0
    retry_count: int = 0
    dead_letter_count: int = 0
    queue_dropped: int = 0


metrics = BridgeMetrics()


def _post(raw: bytes, timeout: float = 5.0) -> None:
    req = request.Request(
        BACKEND_URL,
        data=raw,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(req, timeout=timeout) as response:
        if response.status >= 300:
            raise RuntimeError(f"backend rejected telemetry: {response.status}")


def deliver_with_retries(
    raw: bytes,
    post_fn=_post,
    sleep_fn=time.sleep,
    max_retries: int = MAX_RETRIES,
    success_count: int = 1,
) -> bool:
    for attempt in range(max_retries + 1):
        try:
            post_fn(raw)
            metrics.delivery_success += success_count
            metrics.http_batch_deliveries += 1
            return True
        except Exception as exc:
            if attempt >= max_retries:
                DLQ_PATH.parent.mkdir(parents=True, exist_ok=True)
                with DLQ_PATH.open("a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "timestamp": time.time(),
                                "error": str(exc),
                                "payload": raw.decode("utf-8", errors="replace"),
                            }
                        )
                        + "\n"
                    )
                metrics.dead_letter_count += 1
                log.error("telemetry moved to DLQ after bounded retries: %s", exc)
                return False
            metrics.retry_count += 1
            delay = min(8.0, 0.25 * (2**attempt)) + random.uniform(0, 0.10)
            sleep_fn(delay)
    return False


def collect_batch(
    source_queue: queue.Queue[bytes],
    first: bytes,
    *,
    batch_size: int = BATCH_SIZE,
    flush_ms: float = BATCH_FLUSH_MS,
) -> list[bytes]:
    """Collect a bounded batch, waiting briefly for steady near-term arrivals."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if flush_ms <= 0:
        raise ValueError("flush_ms must be positive")

    batch = [first]
    deadline = time.monotonic() + (flush_ms / 1000.0)
    while len(batch) < batch_size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            batch.append(source_queue.get(timeout=remaining))
        except queue.Empty:
            break
    return batch


def process_one_batch(
    source_queue: queue.Queue[bytes],
    *,
    deliver_fn=deliver_with_retries,
    batch_size: int = BATCH_SIZE,
    flush_ms: float = BATCH_FLUSH_MS,
) -> int:
    """Deliver one bounded batch and complete queue accounting exactly once per item."""
    first = source_queue.get()
    batch = collect_batch(
        source_queue,
        first,
        batch_size=batch_size,
        flush_ms=flush_ms,
    )
    raw = b"[" + b",".join(batch) + b"]"
    try:
        deliver_fn(raw, success_count=len(batch))
    finally:
        for _ in batch:
            source_queue.task_done()
    return len(batch)


def post_worker() -> None:
    while True:
        process_one_batch(messages)


def on_connect(client, _userdata, _flags, reason_code, _properties) -> None:
    if int(reason_code) == 0:
        client.subscribe(TOPIC, qos=1)
        log.info("subscribed to %s", TOPIC)
    else:
        log.error("MQTT connection failed: %s", reason_code)


def on_message(_client, _userdata, message) -> None:
    try:
        json.loads(message.payload.decode("utf-8"))
        messages.put_nowait(message.payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        log.warning("dropped malformed MQTT payload")
    except queue.Full:
        metrics.queue_dropped += 1
        log.error("bounded bridge queue full; dropping message")


def bridge_stats() -> dict[str, int]:
    return {
        "delivery_success": metrics.delivery_success,
        "http_batch_deliveries": metrics.http_batch_deliveries,
        "retry_count": metrics.retry_count,
        "dead_letter_count": metrics.dead_letter_count,
        "queue_depth": messages.qsize(),
        "queue_dropped": metrics.queue_dropped,
    }


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(bridge_stats()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args) -> None:
        return


def start_metrics_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", METRICS_PORT), MetricsHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> None:
    if mqtt is None:
        raise RuntimeError("paho-mqtt is required to run the MQTT bridge")

    threading.Thread(target=post_worker, daemon=True).start()
    start_metrics_server()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    delay = 1.0
    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
            client.loop_forever(retry_first_connection=False)
            delay = 1.0
        except OSError as exc:
            log.warning("broker unavailable (%s); reconnect in %.1fs", exc, delay)
            time.sleep(delay)
            delay = min(delay * 2, 30.0)


if __name__ == "__main__":
    main()
