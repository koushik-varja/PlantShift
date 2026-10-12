# PlantShift final integration freeze — v6

This patch changes integration/security/code-quality surfaces only. It does not alter the validated factory simulation, intervention mechanics, ML methodology, whole-run split, runtime inference logic, paired Monte Carlo, optimizer objectives/NO_ACTION behavior, business-value model, sensitivity/roadmap logic, late-event/idempotency semantics, maintenance system, SSE architecture or frontend information architecture.

Implemented freeze fixes:

1. Root `.dockerignore` protects `.env`, VCS/local Python artifacts, local DBs, frontend host artifacts and generated Joblib files from the root Docker build context while preserving `.env.example`, source/tests, Alembic, package manifests and evaluation metadata.
2. `frontend/.dockerignore` prevents host `node_modules`, build output and frontend-local env files from entering the frontend image context.
3. MQTT bridge batching now waits within a configurable bounded flush window (`50` events / `50 ms` defaults) instead of immediately breaking on transient queue emptiness.
4. Seven v6 tests cover Docker-ignore policy, aggregation, bounded flush, max-batch/task accounting, control-plane rate limiting, >120 telemetry requests without control-bucket 429s, and unchanged validation/admin security.
5. Generic per-IP control-plane rate limiting exempts only `/api/telemetry` and `/api/telemetry/batch`; other API routes remain limited.
6. The E2E benchmark path/metrics explicitly describe the batching/retry bridge and include HTTP batch delivery count without inventing Docker results.
7. High-density Python files were manually reformatted; backend regression and compile checks were rerun. Ruff/mypy themselves remain NOT EXECUTED because registry access is unavailable.

Final measured status: **67 backend tests passed, 0 failed**, smoke PASS, compileall PASS, in-process benchmark executed, Docker E2E NOT EXECUTED, frontend dependency-based build/test NOT EXECUTED, Ruff/mypy NOT EXECUTED.
