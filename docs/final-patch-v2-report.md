> **Historical report:** superseded by `docs/final-correctness-freeze-v4-report.md` and `docs/verification-report.md` for the current repository.

# PlantShift final-v2 surgical patch report

## Existing architecture preserved

The supplied event-calendar factory simulator, paired-seed Monte Carlo foundation, exhaustive portfolio enumeration, runtime ML architecture, persistent telemetry safety controls, MQTT bridge, FastAPI backend, PostgreSQL/Timescale design, SSE path, and React/Vite frontend were preserved. This patch does not introduce a replacement simulator, optimizer, backend architecture, or unrelated technology.

## Exact source modules changed

- `scenario_engine/engine.py`
- `scenario_engine/__init__.py`
- `optimizer/portfolio.py`
- `optimizer/sensitivity.py`
- `optimizer/__init__.py`
- `backend/app/schemas.py`
- `backend/app/main.py`
- `frontend/src/App.tsx`
- `frontend/src/api.ts`
- `tests/test_final_patch.py`
- `pyproject.toml`
- `requirements.txt`
- `README.md`
- `docs/audit-matrix.md`
- `docs/dependency-lock-status.md`
- `docs/verification-report.md`
- `frontend/DEPENDENCY_LOCK_STATUS.md`
- benchmark result JSON files were refreshed/status-corrected

## Maintenance-horizon fix

A fixed maintenance strategy is validated against the simulation horizon before running. A scheduled event at the exact end of the horizon is treated as outside because it cannot affect operations.

Default fixed starts:

- `MAINTENANCE_NOW`: 0h
- `NEXT_SHIFT`: 8h
- `LOW_DEMAND_WINDOW`: 16h

`RUN_TO_FAILURE` and `CONDITION_TRIGGERED` have no fixed scheduled start.

The frontend defaults to 24h, exposes 8/16/24/48/72h, displays the selected window, and blocks an invalid scenario. Backend validation remains authoritative and returns HTTP 422.

## `MAXIMIZE_ESTIMATED_VALUE`

This objective is now genuinely financial. For every feasible candidate and every paired seed, PlantShift calculates:

- estimated production-value delta
- estimated downtime-cost delta
- estimated scrap-cost delta
- estimated rework-cost delta
- estimated energy-cost delta
- estimated maintenance-cost delta
- estimated operating-value delta
- illustrative implementation cost
- estimated net value

The optimizer ranks by **median estimated net value** and reports P10/median/P90. All outputs remain ESTIMATED / ILLUSTRATIVE.

## Operational objective separation

`BALANCED_OPERATIONAL_IMPACT` is the explicit weighted KPI objective. The old `BALANCED` string remains accepted as a backward-compatible API alias. `MAXIMIZE_ESTIMATED_VALUE` no longer uses that operational weighted score.

## UI final patch

Scenario Builder now exposes simulation duration plus decision-relevant maintenance, scheduling, buffer, capacity, quality, and energy parameters. The optimizer exposes the shared horizon and, for `MAXIMIZE_ESTIMATED_VALUE`, editable business assumptions. Result explanation shows the recommended portfolio, illustrative implementation cost, median/P10/P90 estimated net value, and SIMULATED operational deltas.

## New tests

`tests/test_final_patch.py` adds six semantic tests covering:

1. 8h low-demand maintenance rejection,
2. structured API 422 validation,
3. valid maintenance placement / run-to-failure behavior,
4. median-net-value optimizer semantics and output breakdown,
5. financial-assumption-driven portfolio switching,
6. throughput-vs-financial objective divergence.

Final backend result: **40 passed, 0 failed**.

## Remaining environment limitations

A real npm lock/build and uv lock cannot be produced here because external registry/package resolution is unavailable. Docker is not installed, so the full Compose E2E path and real MQTT/PostgreSQL telemetry benchmark are not executed. These limitations are recorded rather than converted into fake passes.
