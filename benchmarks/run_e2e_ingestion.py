from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from urllib import parse, request
from uuid import uuid4

from edge_adapters import LegacyEdgeAdapter
from factory_simulator import FactorySimulator, baseline_config


def get_json(url: str, token: str | None = None) -> dict:
    headers = {"X-Admin-Token": token} if token else {}
    with request.urlopen(request.Request(url, headers=headers), timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="MEASURED Docker E2E benchmark: simulator -> MQTT -> bridge -> HTTP -> DB -> twin")
    parser.add_argument("--mqtt-host", default="localhost")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--backend", default="http://localhost:8000")
    parser.add_argument("--bridge-metrics", default="http://localhost:9102/metrics")
    parser.add_argument("--admin-token", required=True)
    parser.add_argument("--messages", type=int, default=300)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    prefix = f"e2e-{uuid4().hex[:10]}-"
    sim = FactorySimulator(baseline_config(2), seed=88, run_id=prefix.rstrip("-"))
    sim.run()
    source = sim.telemetry[: args.messages]
    if len(source) < args.messages:
        raise RuntimeError(f"simulator produced only {len(source)} events")

    before = get_json(args.bridge_metrics)
    adapter = LegacyEdgeAdapter(args.mqtt_host, args.mqtt_port)
    adapter.connect()
    wall_start = time.perf_counter()
    try:
        for i, raw in enumerate(source):
            event = dict(raw)
            event["event_id"] = f"{prefix}{i:06d}"
            event["timestamp"] = datetime.now(UTC).isoformat()
            event["run_id"] = prefix.rstrip("-")
            adapter.publish(event)
    finally:
        adapter.close()

    stats_url = f"{args.backend}/api/benchmarks/ingestion?{parse.urlencode({'prefix': prefix})}"
    persisted = 0
    db_stats: dict = {}
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        db_stats = get_json(stats_url, args.admin_token)
        persisted = int(db_stats.get("count", 0))
        if persisted >= args.messages:
            break
        time.sleep(0.25)
    wall_elapsed = time.perf_counter() - wall_start
    after = get_json(args.bridge_metrics)
    result = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "label": "MEASURED END-TO-END INGESTION",
        "path": (
            "simulator -> MQTT -> bounded batching/retry bridge -> HTTP API -> validation -> PostgreSQL/Timescale service -> digital twin"
        ),
        "messages_published": args.messages,
        "messages_persisted": persisted,
        "failed_messages": args.messages - persisted,
        "wall_messages_per_sec": round(persisted / max(wall_elapsed, 1e-9), 2),
        "persisted_latency_ms": db_stats.get("latency_ms"),
        "bridge_metric_delta": {
            key: int(after.get(key, 0)) - int(before.get(key, 0))
            for key in (
                "delivery_success",
                "http_batch_deliveries",
                "retry_count",
                "dead_letter_count",
                "queue_dropped",
            )
        },
        "complete": persisted == args.messages,
    }
    path = "benchmarks/results/e2e_ingestion_results.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps(result, indent=2))
    if not result["complete"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
