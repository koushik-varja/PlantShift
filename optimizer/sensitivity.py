from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class BusinessAssumptions:
    value_per_finished_unit: float = 80.0
    downtime_cost_per_hour: float = 200.0
    scrap_cost_per_unit: float = 55.0
    rework_cost_per_unit: float = 18.0
    energy_cost_per_kwh: float = 0.12
    planned_maintenance_cost: float = 90.0
    unplanned_maintenance_cost: float = 220.0


def _maintenance_cost(metrics: dict[str, Any], assumptions: BusinessAssumptions) -> float:
    planned = sum(float(m["maintenance_events"]) for m in metrics["machines"].values())
    failures = sum(float(m["failures"]) for m in metrics["machines"].values())
    return planned * assumptions.planned_maintenance_cost + failures * assumptions.unplanned_maintenance_cost


def operational_value(metrics: dict[str, Any], assumptions: BusinessAssumptions) -> float:
    """Estimated operating value for one simulated period, excluding transformation capex."""

    return (
        float(metrics["throughput_units"]) * assumptions.value_per_finished_unit
        - float(metrics["unplanned_downtime_min"]) / 60.0 * assumptions.downtime_cost_per_hour
        - float(metrics["scrap_units"]) * assumptions.scrap_cost_per_unit
        - float(metrics["rework_units"]) * assumptions.rework_cost_per_unit
        - float(metrics["energy_kwh"]) * assumptions.energy_cost_per_kwh
        - _maintenance_cost(metrics, assumptions)
    )


def financial_effect_components(
    baseline: dict[str, Any],
    scenario: dict[str, Any],
    assumptions: BusinessAssumptions,
    implementation_cost: float | None = None,
) -> dict[str, float]:
    """Transparent estimated financial deltas for one paired simulation.

    Positive component values mean an estimated benefit versus baseline. The
    implementation cost is then subtracted once to produce estimated net value.
    All monetary values use the user's chosen illustrative currency/unit.
    """

    implementation = float(scenario.get("transformation_cost", 0.0) if implementation_cost is None else implementation_cost)
    production_value_delta = (
        float(scenario["throughput_units"]) - float(baseline["throughput_units"])
    ) * assumptions.value_per_finished_unit
    downtime_cost_delta = (
        (float(baseline["unplanned_downtime_min"]) - float(scenario["unplanned_downtime_min"])) / 60.0 * assumptions.downtime_cost_per_hour
    )
    scrap_cost_delta = (float(baseline["scrap_units"]) - float(scenario["scrap_units"])) * assumptions.scrap_cost_per_unit
    rework_cost_delta = (float(baseline["rework_units"]) - float(scenario["rework_units"])) * assumptions.rework_cost_per_unit
    energy_cost_delta = (float(baseline["energy_kwh"]) - float(scenario["energy_kwh"])) * assumptions.energy_cost_per_kwh
    maintenance_cost_delta = _maintenance_cost(baseline, assumptions) - _maintenance_cost(scenario, assumptions)
    operating_effect = (
        production_value_delta + downtime_cost_delta + scrap_cost_delta + rework_cost_delta + energy_cost_delta + maintenance_cost_delta
    )
    return {
        "estimated_production_value_delta": production_value_delta,
        "estimated_downtime_cost_delta": downtime_cost_delta,
        "estimated_scrap_cost_delta": scrap_cost_delta,
        "estimated_rework_cost_delta": rework_cost_delta,
        "estimated_energy_cost_delta": energy_cost_delta,
        "estimated_maintenance_cost_delta": maintenance_cost_delta,
        "estimated_operating_value_delta": operating_effect,
        "illustrative_implementation_cost": implementation,
        "estimated_net_value": operating_effect - implementation,
    }


def business_value(
    baseline: dict[str, Any],
    scenario: dict[str, Any],
    assumptions: BusinessAssumptions,
) -> dict[str, Any]:
    components = financial_effect_components(baseline, scenario, assumptions)
    operating_effect = components["estimated_operating_value_delta"]
    implementation = components["illustrative_implementation_cost"]
    payback = None if operating_effect <= 0 else implementation / operating_effect
    rounded_components = {key: round(value, 2) for key, value in components.items()}
    return {
        "observed_baseline": {
            "throughput_units": baseline["throughput_units"],
            "energy_kwh": baseline["energy_kwh"],
            "unplanned_downtime_min": baseline["unplanned_downtime_min"],
        },
        "simulated_delta": {
            "throughput_units": scenario["throughput_units"] - baseline["throughput_units"],
            "energy_kwh": round(scenario["energy_kwh"] - baseline["energy_kwh"], 3),
            "unplanned_downtime_min": round(scenario["unplanned_downtime_min"] - baseline["unplanned_downtime_min"], 3),
        },
        "estimated_breakdown": rounded_components,
        # Backward-compatible field: operating effect before transformation capex.
        "estimated_financial_effect": round(operating_effect, 2),
        "estimated_net_value": round(components["estimated_net_value"], 2),
        "illustrative_implementation_cost": round(implementation, 2),
        "illustrative_payback_simulation_periods": round(payback, 3) if payback is not None else None,
        "formula": (
            "estimated net value = production-value delta + downtime-cost savings + scrap-cost savings + "
            "rework-cost savings + energy-cost savings + maintenance-cost savings - illustrative implementation cost"
        ),
        "label": "ESTIMATED / ILLUSTRATIVE — NOT ACTUAL OR GUARANTEED ROI",
    }


def sensitivity_stability(
    baseline: dict[str, Any],
    candidates: list[dict[str, Any]],
    assumptions: BusinessAssumptions,
) -> dict[str, Any]:
    if not candidates:
        return {"decision_stability": "UNKNOWN", "winner_counts": {}, "cases_tested": 0}
    factors = [0.8, 1.0, 1.2]
    winners: dict[str, int] = {}
    influence: dict[str, dict[str, dict[str, int]]] = {
        "production_value": {},
        "downtime_cost": {},
        "energy_cost": {},
        "implementation_cost": {},
    }
    tested = 0
    for value_factor in factors:
        for downtime_factor in factors:
            for energy_factor in factors:
                for cost_factor in factors:
                    adjusted = BusinessAssumptions(
                        assumptions.value_per_finished_unit * value_factor,
                        assumptions.downtime_cost_per_hour * downtime_factor,
                        assumptions.scrap_cost_per_unit,
                        assumptions.rework_cost_per_unit,
                        assumptions.energy_cost_per_kwh * energy_factor,
                        assumptions.planned_maintenance_cost,
                        assumptions.unplanned_maintenance_cost,
                    )
                    scored = [
                        (
                            operational_value(item["metrics"], adjusted) - float(item["cost"]) * cost_factor,
                            item["name"],
                        )
                        for item in candidates
                    ]
                    winner = max(scored)[1]
                    winners[winner] = winners.get(winner, 0) + 1
                    tested += 1
                    for key, value in (
                        ("production_value", value_factor),
                        ("downtime_cost", downtime_factor),
                        ("energy_cost", energy_factor),
                        ("implementation_cost", cost_factor),
                    ):
                        influence[key].setdefault(str(value), {})
                        influence[key][str(value)][winner] = influence[key][str(value)].get(winner, 0) + 1
    top_share = max(winners.values()) / tested
    stability = "HIGH" if top_share >= 0.8 else "MEDIUM" if top_share >= 0.6 else "LOW"
    return {
        "decision_stability": stability,
        "winner_counts": winners,
        "winner_share": round(top_share, 3),
        "cases_tested": tested,
        "sensitivity_by_assumption": influence,
        "human_review_recommended": stability == "LOW",
        "label": "SIMULATED / ESTIMATED decision stability, not formal probabilistic confidence",
    }
