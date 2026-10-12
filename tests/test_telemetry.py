from copy import deepcopy

from factory_simulator import FactorySimulator, baseline_config
from telemetry import TelemetryIngestor


def one_event():
    sim = FactorySimulator(baseline_config(1), seed=8)
    sim.run()
    return deepcopy(sim.telemetry[0])


def test_duplicate_detection_and_twin_update():
    ingest = TelemetryIngestor(dedupe_capacity=10)
    event = one_event()
    assert ingest.ingest(event).accepted
    second = ingest.ingest(event)
    assert not second.accepted and second.duplicate
    twin = ingest.twin_store.get(event["machine_id"])
    assert twin is not None and twin["event_count"] == 1


def test_malformed_event_rejected():
    ingest = TelemetryIngestor()
    event = one_event()
    event["wear"] = 9.0
    result = ingest.ingest(event)
    assert not result.accepted and not result.duplicate
    assert ingest.stats()["rejected"] == 1
