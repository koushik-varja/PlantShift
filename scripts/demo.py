from __future__ import annotations

import json

from analytics import diagnose
from optimizer import PortfolioConstraints, build_roadmap, optimize_portfolio
from scenario_engine import Scenario, monte_carlo, run_scenario

if __name__ == "__main__":
    baseline = run_scenario(Scenario("baseline", []), duration_hours=8, seed=7)
    transformed = Scenario(
        "phased-future",
        [
            "iot_retrofit",
            "telemetry_platform",
            "condition_maintenance",
            "optimized_scheduling",
        ],
    )
    future = run_scenario(transformed, duration_hours=8, seed=7)
    mc = monte_carlo(transformed, runs=12, duration_hours=8)
    portfolio = optimize_portfolio(PortfolioConstraints(), duration_hours=4, seed=41)
    roadmap = build_roadmap(portfolio["best"]["interventions"] if portfolio["best"] else [])
    print(
        json.dumps(
            {
                "baseline": baseline,
                "diagnosis": diagnose(baseline),
                "future": future,
                "monte_carlo": mc["summary"],
                "portfolio": portfolio,
                "roadmap": roadmap,
            },
            indent=2,
        )
    )
