from __future__ import annotations

import json
import os
import platform
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psutil
from fastapi.testclient import TestClient

os.environ.setdefault("ADMIN_TOKEN", "benchmark-local-token")
os.environ.setdefault("DATABASE_URL", "sqlite:///./benchmark_plantshift.db")


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * p)))
    return ordered[index]


def sample_event(index: int) -> dict:
    return {
        "event_id": str(uuid4()),
        "run_id": "bench",
        "machine_id": "machineB",
        "stage": "B",
        "timestamp": datetime.now(UTC).isoformat(),
        "sim_minute": float(index) / 10,
        "state": "RUNNING",
        "vibration_mm_s": 2.2,
        "temperature_c": 55.0,
        "load": 0.8,
        "rpm": 1300.0,
        "energy_kw": 8.2,
        "wear": 0.35,
        "cycle_id": f"B-{index}",
        "failure_event": False,
        "production_context": {"process": "Processing"},
    }


def main() -> None:
    # Import application modules only after benchmark-local environment variables are set.
    from backend.app.db import ScenarioRecord, SessionLocal
    from backend.app.main import app
    from optimizer import PortfolioConstraints, optimize_portfolio
    from scenario_engine import Scenario, run_scenario
    from telemetry import TelemetryIngestor

    out = Path("benchmarks/results")
    out.mkdir(parents=True, exist_ok=True)
    result: dict = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "environment": {
            "cpu": platform.processor() or platform.machine(),
            "logical_cpu_count": psutil.cpu_count(),
            "ram_gb": round(psutil.virtual_memory().total / 1024**3, 2),
            "os": platform.platform(),
            "python": platform.python_version(),
        },
        "scenario_size": {
            "factory_stages": 5,
            "machine_assets": 4,
            "scenario_hours": 4,
            "ingestion_messages": 5000,
        },
        "notes": [
            "Synthetic workload",
            "SQLite used for executable benchmark in this environment",
            ("This file contains IN-PROCESS microbenchmarks only; Docker/MQTT E2E is a separate benchmark"),
        ],
    }

    ingestor = TelemetryIngestor(dedupe_capacity=6000)
    latencies = []
    start = time.perf_counter()
    for index in range(5000):
        event_start = time.perf_counter()
        ingestor.ingest(sample_event(index))
        latencies.append((time.perf_counter() - event_start) * 1000)
    elapsed = time.perf_counter() - start
    result["in_process_telemetry_microbenchmark"] = {
        "messages_per_sec": round(5000 / elapsed, 2),
        "latency_ms_p50": round(percentile(latencies, 0.5), 4),
        "latency_ms_p95": round(percentile(latencies, 0.95), 4),
    }
    result["in_process_validation_dedupe_twin_latency_ms"] = {
        "p50": round(percentile(latencies, 0.5), 4),
        "p95": round(percentile(latencies, 0.95), 4),
    }

    scenario_times = []
    for seed in range(5):
        scenario_start = time.perf_counter()
        run_scenario(
            Scenario("bench", ["optimized_scheduling"]),
            duration_hours=4,
            seed=1000 + seed,
        )
        scenario_times.append((time.perf_counter() - scenario_start) * 1000)
    result["scenario_execution_ms"] = {
        "median": round(statistics.median(scenario_times), 3),
        "p95": round(percentile(scenario_times, 0.95), 3),
        "runs": len(scenario_times),
    }

    optimizer_start = time.perf_counter()
    optimized = optimize_portfolio(
        PortfolioConstraints(
            budget=60,
            implementation_capacity=7,
            maximum_risk=5,
        ),
        duration_hours=1,
        seed=77,
    )
    optimizer_ms = (time.perf_counter() - optimizer_start) * 1000
    result["portfolio_optimization"] = {
        "runtime_ms": round(optimizer_ms, 3),
        "feasible_combinations": optimized["evaluated_feasible_combinations"],
    }

    api_latencies = []
    with TestClient(app) as client:
        for _ in range(80):
            api_start = time.perf_counter()
            response = client.get("/api/catalog")
            response.raise_for_status()
            api_latencies.append((time.perf_counter() - api_start) * 1000)
        result["api_catalog_latency_ms"] = {
            "p50": round(percentile(api_latencies, 0.5), 4),
            "p95": round(percentile(api_latencies, 0.95), 4),
            "requests": len(api_latencies),
        }
        response = client.get("/api/baseline?duration_hours=1")
        response.raise_for_status()

    db_latencies = []
    with SessionLocal() as db:
        for _ in range(80):
            db_start = time.perf_counter()
            db.query(ScenarioRecord).order_by(ScenarioRecord.id.desc()).limit(20).all()
            db_latencies.append((time.perf_counter() - db_start) * 1000)
    result["db_query_latency_ms"] = {
        "p50": round(percentile(db_latencies, 0.5), 4),
        "p95": round(percentile(db_latencies, 0.95), 4),
        "database": "SQLite benchmark fallback",
    }

    path = out / "benchmark_results.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
