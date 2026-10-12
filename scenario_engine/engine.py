from __future__ import annotations

import statistics
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from factory_simulator import FactorySimulator, MaintenanceStrategy, baseline_config

from .catalog import CATALOG


@dataclass(slots=True)
class Scenario:
    name: str
    interventions: list[str]
    costs: dict[str, float] | None = None
    efforts: dict[str, int] | None = None
    parameters: dict[str, Any] | None = None


def validate_interventions(ids: Iterable[str]) -> None:
    selected = set(ids)
    unknown = selected - CATALOG.keys()
    if unknown:
        raise ValueError(f"Unknown interventions: {sorted(unknown)}")
    for item in selected:
        missing = set(CATALOG[item].prerequisites) - selected
        if missing:
            raise ValueError(f"{item} requires {sorted(missing)}")


def validate_maintenance_configuration(ids: Iterable[str], parameters: dict[str, Any] | None = None) -> None:
    selected = set(ids)
    if "maintenance_window" not in selected:
        return
    params = parameters or {}
    strategy = MaintenanceStrategy(str(params.get("maintenance_strategy", "LOW_DEMAND_WINDOW")))
    if strategy == MaintenanceStrategy.CONDITION_TRIGGERED:
        raise ValueError("maintenance_window does not accept CONDITION_TRIGGERED; select the condition_maintenance intervention instead.")
    if strategy == MaintenanceStrategy.RUN_TO_FAILURE:
        raise ValueError(
            "RUN_TO_FAILURE is a comparison/baseline policy, not a maintenance_window intervention. Remove maintenance_window."
        )


def maintenance_window_start_min(
    strategy: MaintenanceStrategy | str,
    parameters: dict[str, Any] | None = None,
) -> float | None:
    """Return the explicit start minute for scheduled-maintenance strategies.

    CONDITION_TRIGGERED and RUN_TO_FAILURE are event/condition driven and therefore
    do not have a fixed scheduled start.
    """

    params = parameters or {}
    parsed = strategy if isinstance(strategy, MaintenanceStrategy) else MaintenanceStrategy(str(strategy))
    if parsed in {MaintenanceStrategy.NONE, MaintenanceStrategy.RUN_TO_FAILURE, MaintenanceStrategy.CONDITION_TRIGGERED}:
        return None
    if params.get("maintenance_start_min") is not None:
        return float(params["maintenance_start_min"])
    if parsed == MaintenanceStrategy.MAINTENANCE_NOW:
        return 0.0
    if parsed == MaintenanceStrategy.NEXT_SHIFT:
        return 480.0
    if parsed == MaintenanceStrategy.LOW_DEMAND_WINDOW:
        return 960.0
    return None


def validate_maintenance_horizon(
    ids: Iterable[str],
    duration_hours: float,
    parameters: dict[str, Any] | None = None,
) -> None:
    """Reject scenarios whose selected scheduled maintenance cannot occur.

    The check deliberately uses ``horizon > start`` rather than ``>=`` because a
    maintenance event at the exact simulation end cannot affect operations.
    """

    selected = set(ids)
    if "maintenance_window" not in selected:
        return
    params = parameters or {}
    strategy = MaintenanceStrategy(str(params.get("maintenance_strategy", "LOW_DEMAND_WINDOW")))
    start_min = maintenance_window_start_min(strategy, params)
    if start_min is None:
        return
    horizon_min = float(duration_hours) * 60.0
    if horizon_min <= start_min:
        start_hours = start_min / 60.0
        raise ValueError(
            "Selected maintenance window occurs outside the simulation horizon: "
            f"{strategy.value} starts at {start_hours:g}h, but duration_hours={duration_hours:g}. "
            "Increase the simulation duration so the maintenance event can occur."
        )


def apply_interventions(ids: list[str], duration_hours: float = 8.0, parameters: dict[str, Any] | None = None):
    validate_interventions(ids)
    validate_maintenance_configuration(ids, parameters)
    validate_maintenance_horizon(ids, duration_hours, parameters)
    cfg = baseline_config(duration_hours)
    selected = set(ids)
    p = parameters or {}
    # Retrofit creates observability but is intentionally weaker than a central platform.
    if "iot_retrofit" in selected:
        cfg.iot_visibility = float(p.get("iot_visibility", 0.35))
    if "telemetry_platform" in selected:
        cfg.iot_visibility = max(cfg.iot_visibility, float(p.get("central_visibility", 0.85)))
    if "condition_maintenance" in selected:
        cfg.cbm_enabled = True
        cfg.cbm_threshold = float(p.get("cbm_threshold", 0.62))
        cfg.maintenance_strategy = MaintenanceStrategy.CONDITION_TRIGGERED
        stage = p.get("maintenance_stage")
        if stage is not None:
            if stage not in cfg.machines:
                raise ValueError("maintenance_stage must be one of A/B/C/D")
            cfg.cbm_stages = (str(stage),)
    if "optimized_scheduling" in selected:
        cfg.scheduling_rule = str(p.get("scheduling_rule", "weighted_priority"))
    if "buffer_redesign" in selected:
        cfg.buffer_sizes["B"] = int(p.get("buffer_b", 28))
        cfg.buffer_sizes["C"] = int(p.get("buffer_c", 22))
    if "capacity_addition" in selected:
        stage = str(p.get("capacity_stage", "B"))
        if stage not in cfg.machines:
            raise ValueError("capacity_stage must be one of A/B/C/D")
        cfg.machines[stage].capacity = int(p.get("capacity_count", 2))
        cfg.speed_multipliers[stage] = float(p.get("speed_multiplier", 1.0))
    if "quality_assist" in selected:
        cfg.inspection_delay_min = float(p.get("inspection_delay_min", 0.75))
        cfg.inspection_accuracy = float(p.get("inspection_accuracy", 0.98))
        cfg.defect_detection_rate = float(p.get("defect_detection_rate", 0.96))
    if "maintenance_window" in selected:
        cfg.planned_maintenance_min = float(p.get("planned_maintenance_min", 12.0))
        cfg.maintenance_stage = str(p.get("maintenance_stage", "B"))
        cfg.maintenance_strategy = MaintenanceStrategy(str(p.get("maintenance_strategy", "LOW_DEMAND_WINDOW")))
        if p.get("maintenance_start_min") is not None:
            cfg.maintenance_start_min = float(p["maintenance_start_min"])
    if "energy_efficiency" in selected:
        factor = float(p.get("energy_factor", 0.90))
        for machine in cfg.machines.values():
            machine.base_kw *= factor
    return cfg


def run_scenario(scenario: Scenario, *, duration_hours: float = 8.0, seed: int = 7, demand_seed: int = 2026) -> dict[str, Any]:
    cfg = apply_interventions(scenario.interventions, duration_hours, scenario.parameters)
    sim = FactorySimulator(cfg, seed=seed, demand_seed=demand_seed, run_id=f"{scenario.name}-{seed}")
    metrics = sim.run()
    metrics["scenario"] = scenario.name
    metrics["interventions"] = list(scenario.interventions)
    metrics["transformation_cost"] = round(
        sum((scenario.costs or {}).get(i, CATALOG[i].illustrative_cost) for i in scenario.interventions), 2
    )
    metrics["transformation_effort"] = sum(
        (scenario.efforts or {}).get(i, CATALOG[i].implementation_effort) for i in scenario.interventions
    )
    metrics["transformation_risk"] = sum(CATALOG[i].risk for i in scenario.interventions)
    if "maintenance_window" in scenario.interventions:
        params = scenario.parameters or {}
        strategy = MaintenanceStrategy(str(params.get("maintenance_strategy", "LOW_DEMAND_WINDOW")))
        start_min = maintenance_window_start_min(strategy, params)
        metrics["maintenance_window"] = {
            "strategy": strategy.value,
            "scheduled_start_min": start_min,
            "scheduled_start_hour": None if start_min is None else round(start_min / 60.0, 3),
            "simulation_duration_hours": duration_hours,
        }
    metrics["impact_label"] = "SIMULATED IMPACT"
    return metrics


def _pct_change(value: float | int | None, baseline: float | int | None, inverse: bool = False) -> float | None:
    if value is None or baseline is None or baseline == 0:
        return None
    raw = (float(value) - float(baseline)) / abs(float(baseline)) * 100.0
    return round(-raw if inverse else raw, 3)


def compare_to_baseline(result: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    return {
        "throughput_pct": _pct_change(result["throughput_units"], baseline["throughput_units"]),
        "oee_pct": _pct_change(result["oee"]["oee"], baseline["oee"]["oee"]),
        "downtime_pct_improvement": _pct_change(result["unplanned_downtime_min"], baseline["unplanned_downtime_min"], True),
        "scrap_pct_improvement": _pct_change(result["scrap_rate"], baseline["scrap_rate"], True),
        "lead_time_pct_improvement": _pct_change(result["lead_time_mean_min"], baseline["lead_time_mean_min"], True),
        "late_orders_pct_improvement": _pct_change(result["late_orders"], baseline["late_orders"], True),
        "wip_pct_improvement": _pct_change(result["wip_end"], baseline["wip_end"], True),
        "energy_pct_improvement": _pct_change(result["energy_kwh"], baseline["energy_kwh"], True),
        "energy_per_unit_pct_improvement": _pct_change(
            result["energy_per_finished_unit_kwh"], baseline["energy_per_finished_unit_kwh"], True
        ),
    }


def _summary(vals: list[float]) -> dict[str, float]:
    vals = sorted(vals)
    n = len(vals)
    return {
        "mean": round(statistics.fmean(vals), 3),
        "median": round(statistics.median(vals), 3),
        "p10": round(vals[max(0, round(0.1 * (n - 1)))], 3),
        "p90": round(vals[min(n - 1, round(0.9 * (n - 1)))], 3),
    }


def monte_carlo(
    scenario: Scenario,
    *,
    runs: int = 12,
    duration_hours: float = 8.0,
    demand_seed: int = 2026,
    start_seed: int = 100,
) -> dict[str, Any]:
    if runs < 3:
        raise ValueError("runs must be >= 3")
    # Validate before beginning paired runs so an impossible maintenance choice
    # never degrades into a silent zero-effect scenario.
    validate_maintenance_horizon(scenario.interventions, duration_hours, scenario.parameters)
    seeds = [start_seed + i for i in range(runs)]
    pairs = []
    for seed in seeds:
        baseline = run_scenario(Scenario("baseline", []), duration_hours=duration_hours, seed=seed, demand_seed=demand_seed)
        transformed = run_scenario(scenario, duration_hours=duration_hours, seed=seed, demand_seed=demand_seed)
        pairs.append(compare_to_baseline(transformed, baseline))
    summary = {}
    for key in pairs[0]:
        vals = [float(item[key]) for item in pairs if item[key] is not None]
        if vals:
            summary[key] = _summary(vals)
    return {
        "scenario": asdict(scenario),
        "runs": runs,
        "paired_seeds": seeds,
        "summary": summary,
        "impact_label": "SIMULATED IMPACT",
        "raw_changes": pairs,
    }
