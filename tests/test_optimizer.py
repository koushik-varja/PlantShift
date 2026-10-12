from optimizer import PortfolioConstraints, build_roadmap, optimize_portfolio


def test_roadmap_respects_telemetry_prerequisites():
    phases = build_roadmap(["iot_retrofit", "telemetry_platform", "condition_maintenance"])
    interventions = [intervention for phase in phases for intervention in phase["interventions"]]
    assert interventions.index("iot_retrofit") < interventions.index("telemetry_platform")
    assert interventions.index("telemetry_platform") < interventions.index("condition_maintenance")


def test_optimizer_respects_budget_and_prerequisites():
    constraints = PortfolioConstraints(
        budget=35,
        implementation_capacity=5,
        maximum_risk=4,
    )
    result = optimize_portfolio(constraints, duration_hours=1, seed=5)
    assert result["best"] is not None
    assert result["best"]["cost"] <= 35
