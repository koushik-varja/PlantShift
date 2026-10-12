from __future__ import annotations

from analytics import diagnose
from factory_simulator import FactorySimulator, baseline_config
from scenario_engine import Scenario, run_scenario
from telemetry import TelemetryIngestor


def main() -> None:
    ingestor = TelemetryIngestor()
    sim = FactorySimulator(
        baseline_config(2),
        seed=12,
        telemetry_sink=lambda event: ingestor.ingest(event),
    )
    baseline = sim.run()
    assert ingestor.stats()["accepted"] == len(sim.telemetry)
    assert len(ingestor.twin_store.all()) == 4
    assert diagnose(baseline)
    future = run_scenario(
        Scenario(
            "future",
            [
                "iot_retrofit",
                "telemetry_platform",
                "condition_maintenance",
                "optimized_scheduling",
            ],
        ),
        duration_hours=2,
        seed=12,
    )
    assert future["impact_label"] == "SIMULATED IMPACT"
    print(
        {
            "baseline_throughput": baseline["throughput_units"],
            "future_throughput": future["throughput_units"],
            "telemetry_events": len(sim.telemetry),
            "twins": len(ingestor.twin_store.all()),
        }
    )


if __name__ == "__main__":
    main()
