from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import main as main_mod
from optimizer import BusinessAssumptions, PortfolioConstraints, optimize_portfolio
from scenario_engine import Scenario, run_scenario


def maintenance_scenario(strategy: str) -> Scenario:
    return Scenario(
        f"maintenance-{strategy.lower()}",
        ["iot_retrofit", "maintenance_window"],
        parameters={
            "maintenance_strategy": strategy,
            "maintenance_stage": "B",
            "planned_maintenance_min": 30,
        },
    )


def test_maintenance_horizon_rejects_low_demand_outside_8h() -> None:
    with pytest.raises(ValueError, match="outside the simulation horizon"):
        run_scenario(maintenance_scenario("LOW_DEMAND_WINDOW"), duration_hours=8, seed=17)


def test_backend_returns_structured_422_for_impossible_maintenance_horizon() -> None:
    payload = {
        "name": "invalid-horizon",
        "interventions": ["iot_retrofit", "maintenance_window"],
        "duration_hours": 8,
        "seed": 17,
        "parameters": {
            "maintenance_strategy": "LOW_DEMAND_WINDOW",
            "maintenance_stage": "B",
            "planned_maintenance_min": 30,
        },
    }
    with TestClient(main_mod.app) as client:
        response = client.post("/api/scenarios/run", headers={"X-Admin-Token": "test-token"}, json=payload)
    assert response.status_code == 422
    assert "outside the simulation horizon" in response.json()["detail"]


def test_maintenance_strategies_execute_with_valid_horizons() -> None:
    now = run_scenario(maintenance_scenario("MAINTENANCE_NOW"), duration_hours=8, seed=17)
    low = run_scenario(maintenance_scenario("LOW_DEMAND_WINDOW"), duration_hours=24, seed=17)
    next_shift = run_scenario(maintenance_scenario("NEXT_SHIFT"), duration_hours=24, seed=17)
    run_to_failure = run_scenario(Scenario("maintenance-run-to-failure", ["iot_retrofit"]), duration_hours=8, seed=17)

    assert now["planned_downtime_min"] == 30
    assert low["planned_downtime_min"] == 30
    assert low["maintenance_window"]["scheduled_start_hour"] == 16
    assert next_shift["planned_downtime_min"] == 30
    assert next_shift["maintenance_window"]["scheduled_start_hour"] == 8
    assert run_to_failure["planned_downtime_min"] == 0


def test_estimated_value_score_is_median_net_financial_value() -> None:
    result = optimize_portfolio(
        PortfolioConstraints(
            budget=60,
            implementation_capacity=7,
            maximum_risk=5,
            objective="MAXIMIZE_ESTIMATED_VALUE",
            evaluation_runs=3,
        ),
        duration_hours=4,
        seed=4,
    )
    best = result["best"]
    assert best is not None
    assert best["score"] == best["estimated_value"]["estimated_net_value"]["median"]
    assert {
        "estimated_production_value_delta",
        "estimated_downtime_cost_delta",
        "estimated_scrap_cost_delta",
        "estimated_energy_cost_delta",
        "estimated_maintenance_cost_delta",
        "estimated_net_value",
    } <= set(best["estimated_value"])
    assert result["business_assumptions"]["label"] == "ILLUSTRATIVE SAMPLE VALUES / USER-CONFIGURABLE"


def test_financial_assumptions_can_change_selected_portfolio() -> None:
    common = dict(
        budget=60,
        implementation_capacity=7,
        maximum_risk=5,
        objective="MAXIMIZE_ESTIMATED_VALUE",
        evaluation_runs=3,
    )
    low_energy = optimize_portfolio(
        PortfolioConstraints(
            **common,
            business_assumptions=BusinessAssumptions(
                value_per_finished_unit=5,
                downtime_cost_per_hour=10,
                scrap_cost_per_unit=2,
                rework_cost_per_unit=1,
                energy_cost_per_kwh=0.01,
                planned_maintenance_cost=10,
                unplanned_maintenance_cost=20,
            ),
        ),
        duration_hours=4,
        seed=4,
    )
    high_energy = optimize_portfolio(
        PortfolioConstraints(
            **common,
            business_assumptions=BusinessAssumptions(
                value_per_finished_unit=5,
                downtime_cost_per_hour=10,
                scrap_cost_per_unit=2,
                rework_cost_per_unit=1,
                energy_cost_per_kwh=10,
                planned_maintenance_cost=10,
                unplanned_maintenance_cost=20,
            ),
        ),
        duration_hours=4,
        seed=4,
    )
    assert low_energy["best"]["interventions"] != high_energy["best"]["interventions"]
    assert "energy_efficiency" in high_energy["best"]["interventions"]


def test_throughput_and_financial_objectives_can_choose_different_portfolios() -> None:
    assumptions = BusinessAssumptions(
        value_per_finished_unit=5,
        downtime_cost_per_hour=10,
        scrap_cost_per_unit=2,
        rework_cost_per_unit=1,
        energy_cost_per_kwh=10,
        planned_maintenance_cost=10,
        unplanned_maintenance_cost=20,
    )
    costs = {"capacity_addition": 55.0, "energy_efficiency": 5.0}
    base = dict(
        budget=60,
        implementation_capacity=7,
        maximum_risk=5,
        evaluation_runs=3,
        cost_overrides=costs,
        business_assumptions=assumptions,
    )
    throughput = optimize_portfolio(PortfolioConstraints(**base, objective="MAXIMIZE_THROUGHPUT"), duration_hours=4, seed=4)
    financial = optimize_portfolio(PortfolioConstraints(**base, objective="MAXIMIZE_ESTIMATED_VALUE"), duration_hours=4, seed=4)
    assert throughput["best"]["interventions"] == ["capacity_addition"]
    assert financial["best"]["interventions"] == ["energy_efficiency"]
