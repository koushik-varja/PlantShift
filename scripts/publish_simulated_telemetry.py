from __future__ import annotations

import argparse
import os
import time

from edge_adapters import LegacyEdgeAdapter
from factory_simulator import FactorySimulator, baseline_config

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publish PlantShift synthetic machine events over MQTT")
    parser.add_argument("--host", default=os.getenv("MQTT_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MQTT_PORT", "1883")))
    parser.add_argument("--sleep", type=float, default=0.01, help="wall-clock delay between simulated events")
    args = parser.parse_args()
    sim = FactorySimulator(baseline_config(2), seed=31)
    sim.run()
    adapter = LegacyEdgeAdapter(args.host, args.port)
    adapter.connect()
    try:
        for event in sim.telemetry:
            adapter.publish(event)
            time.sleep(max(0, args.sleep))
    finally:
        adapter.close()
    print(f"published {len(sim.telemetry)} synthetic events")
