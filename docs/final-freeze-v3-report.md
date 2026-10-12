> **Historical report:** superseded by `docs/final-correctness-freeze-v4-report.md` and `docs/verification-report.md` for the current repository.

# PlantShift final-v3 freeze patch

This patch changes only the final freeze items requested. It does not replace or redesign the factory simulator, optimizer, ML methodology, telemetry system, business-value model, maintenance mechanics, or frontend architecture.

## Files/modules changed

- `backend/app/main.py` — sensitivity seed/horizon consistency validation.
- `scripts/train_ml.py` — `--if-missing`, `--force`, artifact-readiness validation, direct-script import robustness.
- `backend/Dockerfile` — clean-clone startup order: train-if-missing -> migrate -> FastAPI.
- `tests/test_freeze_patch.py` — sensitivity and ML startup tests.
- `frontend/src/uiLogic.ts` — extracted existing horizon/objective UI logic for direct behavior testing.
- `frontend/src/api.ts` — extracted existing SSE subscription into a testable helper; native EventSource reconnect behavior remains intact.
- `frontend/src/App.tsx` — uses the extracted helpers and accepts optional test initialization props; normal defaults are unchanged.
- `frontend/src/App.test.tsx` — focused UI behavior tests.
- verification/dependency documentation and measured benchmark result metadata.

## Sensitivity consistency

Mixed `seed` or mixed `duration_hours` candidates now receive HTTP 422. Valid candidates share one baseline configuration and are executed with that same validated configuration.

## Clean-clone runtime ML

The generated joblib remains gitignored. A clean backend container now creates it only if the model or required evaluation metadata is absent. Existing artifacts are reused; `--force` is the explicit retrain path.

## Tests

Backend/Python: **47 passed, 0 failed**.

Frontend Vitest tests were added but cannot be executed in this environment because dependencies cannot be resolved/installed. The pure maintenance/objective UI logic was executed directly with Node and passed. Production frontend build is not claimed.

## Locks/build

No `package-lock.json` or `uv.lock` is fabricated. npm registry resolution times out and required uv metadata is not cached. `npm lint/test/build` cannot be fully executed without the missing packages.

## Docker/E2E

Docker is not installed in this environment. Full Docker E2E and the real ingestion benchmark are **NOT EXECUTED**.

## Startup

```bash
docker compose up --build
```

With the final backend image, this performs runtime ML train-if-missing, Alembic migration, then Uvicorn startup.
