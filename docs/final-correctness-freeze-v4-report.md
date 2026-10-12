# PlantShift final-v4 correctness freeze patch

This patch is deliberately surgical. It does not replace the simulator, optimizer, telemetry architecture, business-value engine, maintenance-window mechanism, runtime ML architecture, sensitivity engine, or frontend structure.

## Corrected areas

1. Same-batch duplicate `event_id` handling now preserves the first successfully accepted event instance consistently in DB and twin state.
2. ML train/validation/test splitting is chronological by whole `run_id`, with no run crossing a partition boundary; model/evaluation artifacts were regenerated.
3. Simulator condition-based maintenance now uses a bounded transparent observable-sensor condition score rather than latent wear.
4. Maintenance policy comparison now holds IoT visibility, duration, stochastic seed and demand seed constant.
5. `maintenance_window` exposes only scheduled policies; `condition_maintenance` handles condition-triggered maintenance; run-to-failure is a comparison policy.
6. Pytest environment configuration is deterministic through `tests/conftest.py`; key suites pass independently.
7. Admin token entry is global, password-style, page-memory-only and shared across protected UI workflows.
8. Frontend Docker build is lockfile-aware and uses `npm ci` when a genuine package lock exists.
9. Train-if-missing readiness now rejects corrupt/non-loadable internal Joblib artifacts and verifies required model-bundle keys.
10. Documentation now reflects the whole-run ML split, observable CBM, apples-to-apples maintenance comparison, illustrative monetary-unit semantics, and selected-period estimated net value.

See `docs/verification-report.md` for executed checks and environment limitations.
