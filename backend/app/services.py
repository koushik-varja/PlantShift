from __future__ import annotations

import time
from typing import Any

from analytics import diagnose
from scenario_engine import Scenario, run_scenario

from .db import ScenarioRecord, SessionLocal


def execute_scenario(
    name: str,
    interventions: list[str],
    duration_hours: float,
    seed: int,
    parameters: dict[str, Any],
    costs: dict[str, float] | None = None,
    efforts: dict[str, int] | None = None,
) -> dict[str, Any]:
    start = time.perf_counter()
    result = run_scenario(
        Scenario(
            name,
            interventions,
            costs=costs,
            efforts=efforts,
            parameters=parameters,
        ),
        duration_hours=duration_hours,
        seed=seed,
    )
    result["diagnosis"] = diagnose(result)
    elapsed = (time.perf_counter() - start) * 1000
    with SessionLocal() as db:
        db.add(
            ScenarioRecord(
                name=name,
                interventions={
                    "ids": interventions,
                    "parameters": parameters,
                    "cost_overrides": costs or {},
                    "effort_overrides": efforts or {},
                },
                result=result,
                duration_ms=elapsed,
            )
        )
        db.commit()
    result["execution_ms"] = round(elapsed, 3)
    return result


def maintenance_window_comparison(
    stage: str,
    duration_hours: float,
    seed: int,
    planned_duration_min: float = 30,
) -> list[dict[str, Any]]:
    strategies = [
        "MAINTENANCE_NOW",
        "NEXT_SHIFT",
        "LOW_DEMAND_WINDOW",
        "RUN_TO_FAILURE",
    ]
    demand_seed = 2026
    rows = []
    for strategy in strategies:
        if strategy == "RUN_TO_FAILURE":
            scenario = Scenario(strategy.lower(), ["iot_retrofit"])
        else:
            scenario = Scenario(
                strategy.lower(),
                ["iot_retrofit", "maintenance_window"],
                parameters={
                    "maintenance_stage": stage,
                    "maintenance_strategy": strategy,
                    "planned_maintenance_min": planned_duration_min,
                },
            )
        result = run_scenario(
            scenario,
            duration_hours=duration_hours,
            seed=seed,
            demand_seed=demand_seed,
        )
        rows.append(
            {
                "option": strategy,
                "throughput_units": result["throughput_units"],
                "planned_downtime_min": result["planned_downtime_min"],
                "unplanned_downtime_min": result["unplanned_downtime_min"],
                "late_orders": result["late_orders"],
                "average_input_queue": result["average_queue_lengths"].get(stage, 0),
                "failure_count": sum(machine["failures"] for machine in result["machines"].values()),
                "energy_kwh": result["energy_kwh"],
                "label": "SIMULATED IMPACT",
            }
        )
    return rows
