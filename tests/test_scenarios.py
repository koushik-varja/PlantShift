import pytest

from scenario_engine import Scenario, apply_interventions, monte_carlo


def test_prerequisite_enforced():
    with pytest.raises(ValueError):
        apply_interventions(["condition_maintenance"], 2)


def test_iot_does_not_change_nominal_machine_capacity_or_speed():
    baseline = apply_interventions([], 2)
    iot = apply_interventions(["iot_retrofit"], 2)
    assert baseline.machines["B"].capacity == iot.machines["B"].capacity
    assert baseline.machines["B"].cycle_time_min == iot.machines["B"].cycle_time_min
    assert iot.iot_visibility > baseline.iot_visibility


def test_capacity_intervention_changes_capacity():
    config = apply_interventions(
        ["capacity_addition"],
        2,
        {"capacity_stage": "B", "capacity_count": 2},
    )
    assert config.machines["B"].capacity == 2


def test_monte_carlo_returns_percentiles():
    scenario = Scenario("sched", ["optimized_scheduling"])
    result = monte_carlo(scenario, runs=3, duration_hours=1)
    assert result["runs"] == 3
    assert result["impact_label"] == "SIMULATED IMPACT"
