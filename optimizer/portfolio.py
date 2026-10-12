from __future__ import annotations

import itertools
import statistics
from dataclasses import dataclass, field
from typing import Any

from scenario_engine import CATALOG, Scenario, run_scenario, validate_maintenance_horizon

from .sensitivity import BusinessAssumptions, financial_effect_components

OBJECTIVES = {
    "MAXIMIZE_THROUGHPUT",
    "MAXIMIZE_OEE",
    "MINIMIZE_DOWNTIME",
    "MINIMIZE_SCRAP",
    "MINIMIZE_ENERGY",
    "MINIMIZE_LATE_ORDERS",
    "MAXIMIZE_ESTIMATED_VALUE",
    "MAXIMIZE_BENEFIT_PER_EFFORT",
    "BALANCED_OPERATIONAL_IMPACT",
    "BALANCED",  # backward-compatible alias
}
DEFAULT_WEIGHTS = {
    "throughput": 1.0,
    "oee": 1.0,
    "downtime": 1.0,
    "scrap": 1.0,
    "energy": 1.0,
    "late_orders": 1.0,
}
FINANCIAL_KEYS = (
    "estimated_production_value_delta",
    "estimated_downtime_cost_delta",
    "estimated_scrap_cost_delta",
    "estimated_rework_cost_delta",
    "estimated_energy_cost_delta",
    "estimated_maintenance_cost_delta",
    "estimated_operating_value_delta",
    "estimated_net_value",
)


@dataclass(slots=True)
class PortfolioConstraints:
    budget: float = 100.0
    implementation_capacity: int = 10
    maximum_risk: int = 8
    objective: str = "MAXIMIZE_BENEFIT_PER_EFFORT"
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    evaluation_runs: int = 5
    cost_overrides: dict[str, float] = field(default_factory=dict)
    effort_overrides: dict[str, int] = field(default_factory=dict)
    business_assumptions: BusinessAssumptions = field(default_factory=BusinessAssumptions)
    scenario_parameters: dict[str, Any] = field(default_factory=dict)


def _cost(intervention_id: str, constraints: PortfolioConstraints) -> float:
    return float(constraints.cost_overrides.get(intervention_id, CATALOG[intervention_id].illustrative_cost))


def _effort(intervention_id: str, constraints: PortfolioConstraints) -> int:
    return int(constraints.effort_overrides.get(intervention_id, CATALOG[intervention_id].implementation_effort))


def _valid_combo(combo: tuple[str, ...], constraints: PortfolioConstraints) -> bool:
    selected = set(combo)
    return (
        sum(_cost(i, constraints) for i in combo) <= constraints.budget
        and sum(_effort(i, constraints) for i in combo) <= constraints.implementation_capacity
        and sum(CATALOG[i].risk for i in combo) <= constraints.maximum_risk
        and all(set(CATALOG[i].prerequisites).issubset(selected) for i in combo)
    )


def _stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    n = len(ordered)
    return {
        "median": round(statistics.median(ordered), 4),
        "p10": round(ordered[max(0, round(0.1 * (n - 1)))], 4),
        "p90": round(ordered[min(n - 1, round(0.9 * (n - 1)))], 4),
    }


def _zero_stats() -> dict[str, float]:
    return {"median": 0.0, "p10": 0.0, "p90": 0.0}


def _baseline_candidate(seeds: list[int], objective: str) -> dict[str, Any]:
    return {
        "decision": "NO_ACTION",
        "interventions": [],
        "cost": 0.0,
        "implementation_cost": 0.0,
        "effort": 0,
        "risk": 0,
        "score": 0.0,
        "score_label": (
            "ESTIMATED median net value" if objective == "MAXIMIZE_ESTIMATED_VALUE" else "SIMULATED robust operational objective"
        ),
        "robust_deltas": {key: _zero_stats() for key in DEFAULT_WEIGHTS},
        "estimated_value": {key: _zero_stats() for key in FINANCIAL_KEYS},
        "paired_seeds": seeds,
    }


def _operational_composite(
    robust_deltas: dict[str, dict[str, float]],
    weights: dict[str, float],
) -> float:
    medians = {key: value["median"] for key, value in robust_deltas.items()}
    return sum(weights[key] * medians[key] for key in DEFAULT_WEIGHTS)


def _score(
    robust_deltas: dict[str, dict[str, float]],
    estimated_value: dict[str, dict[str, float]],
    objective: str,
    effort: int,
    weights: dict[str, float],
) -> float:
    med = {key: value["median"] for key, value in robust_deltas.items()}
    if objective == "MAXIMIZE_THROUGHPUT":
        return med["throughput"]
    if objective == "MAXIMIZE_OEE":
        return med["oee"]
    if objective == "MINIMIZE_DOWNTIME":
        return med["downtime"]
    if objective == "MINIMIZE_SCRAP":
        return med["scrap"]
    if objective == "MINIMIZE_ENERGY":
        return med["energy"]
    if objective == "MINIMIZE_LATE_ORDERS":
        return med["late_orders"]
    if objective == "MAXIMIZE_ESTIMATED_VALUE":
        return estimated_value["estimated_net_value"]["median"]
    operational_composite = _operational_composite(robust_deltas, weights)
    if objective == "MAXIMIZE_BENEFIT_PER_EFFORT":
        return operational_composite / max(1, effort)
    return operational_composite


def optimize_portfolio(
    constraints: PortfolioConstraints,
    *,
    duration_hours: float = 24.0,
    seed: int = 41,
) -> dict[str, Any]:
    if constraints.objective not in OBJECTIVES:
        raise ValueError(f"unsupported objective: {constraints.objective}")
    if constraints.evaluation_runs < 3:
        raise ValueError("evaluation_runs must be >= 3")
    if any(key not in DEFAULT_WEIGHTS or value < 0 for key, value in constraints.weights.items()):
        raise ValueError("balanced weights must use known metrics and be non-negative")

    weights = {**DEFAULT_WEIGHTS, **constraints.weights}
    seeds = [seed + i for i in range(constraints.evaluation_runs)]
    ids = tuple(CATALOG)
    transformation_candidates: list[dict[str, Any]] = []
    horizon_exclusions: list[dict[str, Any]] = []
    baselines = {
        current_seed: run_scenario(Scenario("baseline", []), duration_hours=duration_hours, seed=current_seed) for current_seed in seeds
    }

    for size in range(1, len(ids) + 1):
        for combo in itertools.combinations(ids, size):
            if not _valid_combo(combo, constraints):
                continue
            try:
                validate_maintenance_horizon(combo, duration_hours, constraints.scenario_parameters)
            except ValueError as exc:
                horizon_exclusions.append({"interventions": list(combo), "reason": str(exc)})
                continue

            deltas: dict[str, list[float]] = {key: [] for key in DEFAULT_WEIGHTS}
            financial_samples: dict[str, list[float]] = {key: [] for key in FINANCIAL_KEYS}
            implementation_cost = round(sum(_cost(i, constraints) for i in combo), 2)

            for current_seed in seeds:
                baseline = baselines[current_seed]
                transformed = run_scenario(
                    Scenario(
                        "portfolio",
                        list(combo),
                        costs=constraints.cost_overrides,
                        efforts=constraints.effort_overrides,
                        parameters=constraints.scenario_parameters,
                    ),
                    duration_hours=duration_hours,
                    seed=current_seed,
                )
                deltas["throughput"].append(float(transformed["throughput_units"] - baseline["throughput_units"]))
                deltas["oee"].append(float(transformed["oee"]["oee"] - baseline["oee"]["oee"]) * 100.0)
                deltas["downtime"].append(float(baseline["unplanned_downtime_min"] - transformed["unplanned_downtime_min"]))
                deltas["scrap"].append(float(baseline["scrap_rate"] - transformed["scrap_rate"]) * 100.0)
                deltas["energy"].append(float(baseline["energy_kwh"] - transformed["energy_kwh"]))
                deltas["late_orders"].append(float(baseline["late_orders"] - transformed["late_orders"]))
                components = financial_effect_components(
                    baseline,
                    transformed,
                    constraints.business_assumptions,
                    implementation_cost,
                )
                for key in financial_samples:
                    financial_samples[key].append(float(components[key]))

            robust = {key: _stats(values) for key, values in deltas.items()}
            estimated_value = {key: _stats(values) for key, values in financial_samples.items()}
            effort = sum(_effort(i, constraints) for i in combo)
            score = _score(robust, estimated_value, constraints.objective, effort, weights)
            transformation_candidates.append(
                {
                    "decision": "TRANSFORM",
                    "interventions": list(combo),
                    "cost": implementation_cost,
                    "implementation_cost": implementation_cost,
                    "effort": effort,
                    "risk": sum(CATALOG[i].risk for i in combo),
                    "score": round(score, 6),
                    "score_label": (
                        "ESTIMATED median net value"
                        if constraints.objective == "MAXIMIZE_ESTIMATED_VALUE"
                        else "SIMULATED robust operational objective"
                    ),
                    "robust_deltas": robust,
                    "estimated_value": estimated_value,
                    "paired_seeds": seeds,
                }
            )

    candidates = [_baseline_candidate(seeds, constraints.objective), *transformation_candidates]
    candidates.sort(
        key=lambda item: (
            item["score"],
            -float(item["implementation_cost"]),
            -int(item["effort"]),
            -int(item["risk"]),
        ),
        reverse=True,
    )
    best = candidates[0]
    financial_objective = constraints.objective == "MAXIMIZE_ESTIMATED_VALUE"
    no_action = best["decision"] == "NO_ACTION"
    alternatives = [candidate for candidate in transformation_candidates if candidate is not best]
    alternatives.sort(key=lambda item: item["score"], reverse=True)

    return {
        "objective": constraints.objective,
        "objective_semantics": (
            "ESTIMATED financial net value using user-configurable business assumptions and median paired-seed results"
            if financial_objective
            else "SIMULATED operational KPI objective; BALANCED/BALANCED_OPERATIONAL_IMPACT uses user-configurable weights"
        ),
        "weights": weights,
        "business_assumptions": {
            "value_per_finished_unit": constraints.business_assumptions.value_per_finished_unit,
            "downtime_cost_per_hour": constraints.business_assumptions.downtime_cost_per_hour,
            "scrap_cost_per_unit": constraints.business_assumptions.scrap_cost_per_unit,
            "rework_cost_per_unit": constraints.business_assumptions.rework_cost_per_unit,
            "energy_cost_per_kwh": constraints.business_assumptions.energy_cost_per_kwh,
            "planned_maintenance_cost": constraints.business_assumptions.planned_maintenance_cost,
            "unplanned_maintenance_cost": constraints.business_assumptions.unplanned_maintenance_cost,
            "label": "ILLUSTRATIVE SAMPLE VALUES / USER-CONFIGURABLE",
        },
        "constraints": {
            "budget": constraints.budget,
            "implementation_capacity": constraints.implementation_capacity,
            "maximum_risk": constraints.maximum_risk,
            "evaluation_runs": constraints.evaluation_runs,
            "duration_hours": duration_hours,
        },
        "decision": best["decision"],
        "best": best,
        "alternatives": alternatives[:5],
        "explanation": {
            "why": (
                "No transformation portfolio improves the selected objective under the current assumptions and constraints."
                if no_action
                else (
                    "Highest median ESTIMATED net value among feasible portfolios; each candidate used paired baseline/transformed seeds."
                    if financial_objective
                    else (
                        "Highest robust operational objective score among feasible "
                        "portfolios; each candidate used paired baseline/transformed seeds."
                    )
                )
            ),
            "caveat": "SIMULATED operational effects and ESTIMATED financial effects are not guaranteed real-world outcomes.",
        },
        "impact_label": "SIMULATED operational deltas / ESTIMATED financial value / ILLUSTRATIVE assumptions",
        "evaluated_feasible_combinations": len(transformation_candidates),
        "excluded_for_maintenance_horizon": horizon_exclusions,
    }
