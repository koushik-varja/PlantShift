from __future__ import annotations

import json
import queue
import threading
import time
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import main as main_mod
from factory_simulator import FactorySimulator, baseline_config
from scripts import mqtt_bridge


def _sample_event() -> dict:
    simulator = FactorySimulator(baseline_config(1), seed=606)
    simulator.run()
    return deepcopy(simulator.telemetry[0])


def test_root_and_frontend_dockerignores_protect_local_secrets_and_build_artifacts() -> None:
    root_entries = {
        line.strip()
        for line in Path(".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert {
        ".env",
        ".git",
        ".git/**",
        ".venv",
        "venv",
        "__pycache__",
        "**/__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "*.pyc",
        "*.db",
        "frontend/node_modules",
        "frontend/dist",
        "ml/artifacts/*.joblib",
        "benchmarks/results/*.tmp",
    } <= root_entries
    assert ".env.example" not in root_entries

    frontend_entries = {
        line.strip()
        for line in Path("frontend/.dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert {"node_modules", "dist", ".env", ".env.*", ".vite", "coverage"} <= frontend_entries
    assert "package.json" not in frontend_entries
    assert "package-lock.json" not in frontend_entries
    assert "src" not in frontend_entries


def test_bridge_collects_steady_arrivals_into_one_delivery() -> None:
    source: queue.Queue[bytes] = queue.Queue()
    source.put(b'{"id":0}')
    deliveries: list[list[dict[str, int]]] = []

    def producer() -> None:
        for index in range(1, 5):
            time.sleep(0.003)
            source.put(json.dumps({"id": index}).encode("utf-8"))

    def deliver(raw: bytes, *, success_count: int) -> bool:
        payload = json.loads(raw.decode("utf-8"))
        assert success_count == len(payload)
        deliveries.append(payload)
        return True

    producer_thread = threading.Thread(target=producer)
    producer_thread.start()
    collected = mqtt_bridge.process_one_batch(
        source,
        deliver_fn=deliver,
        batch_size=10,
        flush_ms=50,
    )
    producer_thread.join(timeout=1)
    source.join()

    assert collected == 5
    assert len(deliveries) == 1
    assert len(deliveries[0]) == 5
    assert [item["id"] for item in deliveries[0]] == list(range(5))


def test_bridge_single_message_flushes_within_bounded_window() -> None:
    source: queue.Queue[bytes] = queue.Queue()
    source.put(b'{"id":1}')
    delivered: list[bytes] = []

    def deliver(raw: bytes, *, success_count: int) -> bool:
        assert success_count == 1
        delivered.append(raw)
        return True

    started = time.monotonic()
    count = mqtt_bridge.process_one_batch(
        source,
        deliver_fn=deliver,
        batch_size=10,
        flush_ms=20,
    )
    elapsed = time.monotonic() - started
    source.join()

    assert count == 1
    assert len(delivered) == 1
    assert elapsed < 0.25


def test_bridge_respects_max_batch_size_and_queue_accounting() -> None:
    source: queue.Queue[bytes] = queue.Queue()
    for index in range(5):
        source.put(json.dumps({"id": index}).encode("utf-8"))
    sizes: list[int] = []

    def deliver(raw: bytes, *, success_count: int) -> bool:
        sizes.append(len(json.loads(raw.decode("utf-8"))))
        assert success_count == sizes[-1]
        return True

    first_count = mqtt_bridge.process_one_batch(
        source,
        deliver_fn=deliver,
        batch_size=3,
        flush_ms=20,
    )
    second_count = mqtt_bridge.process_one_batch(
        source,
        deliver_fn=deliver,
        batch_size=3,
        flush_ms=20,
    )
    source.join()

    assert first_count == 3
    assert second_count == 2
    assert sizes == [3, 2]
    assert source.empty()


def test_control_plane_rate_limit_still_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod, "RATE_LIMIT_PER_MINUTE", 3)
    main_mod.requests_by_ip.clear()
    with TestClient(main_mod.app) as client:
        statuses = [client.get("/api/catalog").status_code for _ in range(4)]
    main_mod.requests_by_ip.clear()
    assert statuses == [200, 200, 200, 429]


def test_telemetry_is_exempt_from_low_control_plane_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod, "RATE_LIMIT_PER_MINUTE", 2)
    main_mod.requests_by_ip.clear()
    event = _sample_event()

    with TestClient(main_mod.app) as client:
        statuses = []
        for index in range(125):
            request_event = deepcopy(event)
            request_event["event_id"] = f"v6-rate-{index:04d}"
            statuses.append(client.post("/api/telemetry", json=request_event).status_code)
        catalog_status = client.get("/api/catalog").status_code

    main_mod.requests_by_ip.clear()
    assert 429 not in statuses
    assert all(status == 200 for status in statuses)
    assert catalog_status == 200


def test_telemetry_validation_limits_and_admin_controls_remain_enforced() -> None:
    event = _sample_event()
    oversized = []
    for index in range(201):
        item = deepcopy(event)
        item["event_id"] = f"v6-batch-{index:04d}"
        oversized.append(item)

    with TestClient(main_mod.app) as client:
        malformed = client.post("/api/telemetry", json={"not": "telemetry"})
        too_large = client.post("/api/telemetry/batch", json=oversized)
        protected = client.post(
            "/api/scenarios/run",
            json={
                "name": "protected",
                "interventions": [],
                "duration_hours": 1,
                "seed": 1,
                "parameters": {},
            },
        )

    assert malformed.status_code == 422
    assert too_large.status_code == 422
    assert protected.status_code == 403
