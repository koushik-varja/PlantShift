from factory_simulator import FactorySimulator, MachineState, baseline_config


def test_baseline_produces_consistent_metrics():
    sim = FactorySimulator(baseline_config(2), seed=11, demand_seed=77)
    m = sim.run()
    assert m["demand_created"] > 0
    assert 0 <= m["throughput_units"] <= m["demand_created"]
    assert m["wip_end"] >= 0
    assert 0 <= m["oee"]["oee"] <= 1
    assert m["oee"]["oee"] == round(
        m["oee"]["availability"] * m["oee"]["performance"] * m["oee"]["quality"],
        4,
    )
    assert len(sim.telemetry) > 20


def test_telemetry_tracks_degradation_not_independent_noise():
    sim = FactorySimulator(baseline_config(5), seed=22, demand_seed=77)
    sim.run()
    values = [
        event
        for event in sim.telemetry
        if event["machine_id"] == "machineB" and event["state"] in {MachineState.RUNNING.value, MachineState.DEGRADED.value}
    ]
    low = [event["vibration_mm_s"] for event in values if event["wear"] < 0.4]
    high = [event["vibration_mm_s"] for event in values if event["wear"] >= 0.4]
    if high:
        assert sum(high) / len(high) > sum(low) / len(low)


def test_small_buffer_does_not_drop_created_demand():
    cfg = baseline_config(2)
    cfg.buffer_sizes["A"] = 1
    sim = FactorySimulator(cfg, seed=3, demand_seed=4)
    m = sim.run()
    assert m["demand_created"] < 100
    assert m["demand_created"] >= m["throughput_units"] + m["scrap_units"]
