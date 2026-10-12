# PlantShift final correctness freeze — v5

This patch changes no project architecture and adds no product feature. It fixes three correctness issues and records two unavailable quality-tool checks honestly.

## Correctness changes

1. **Late runtime telemetry:** late/out-of-order events remain historically persisted but are excluded from the live ML rolling feature history and cannot replace current health output.
2. **Optimizer baseline:** all objectives include an explicit zero-cost `NO_ACTION` candidate. If no transformation improves the selected objective, the optimizer says so directly while still returning ranked transformation alternatives.
3. **Displayed baseline consistency:** `/api/baseline` supports up to 72h, and the frontend refetches the current-state baseline using the transformed scenario's exact horizon and seed before displaying the pair.

## Regression result

- Full Python suite: **60 passed, 0 failed**.
- v4 freeze suite independently: **8 passed**.
- final-patch suite independently: **6 passed**.
- freeze-patch suite independently: **7 passed**.
- upgrade-acceptance suite independently: **18 passed**.
- new v5 suite independently: **5 passed**.
- smoke workflow: **PASS**.
- Python compileall: **PASS**.
- in-process benchmark: **PASS**.

## Unavailable checks

Ruff and mypy are not installed and the Python package registry is unreachable, so neither check is claimed as passed. Frontend registry access is also unavailable; no `package-lock.json` is fabricated and npm lint/test/build are not claimed as successful. Docker is absent, so Compose E2E and real MQTT/PostgreSQL ingestion benchmarks remain **NOT EXECUTED**.
