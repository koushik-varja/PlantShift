# Dependency lock status — final-v7

## Python

Application/dev dependency versions remain pinned in `pyproject.toml`, `requirements.txt`, and `requirements-dev.txt`.

A resolver-generated Python lock was attempted with:

```bash
uv lock --offline
```

It failed because required registry metadata, beginning with `alembic==1.18.4`, is not present in the local uv cache while networking is disabled. No hand-written `uv.lock` is provided.

On a network-enabled machine:

```bash
uv lock
uv sync --all-extras --frozen
python -m ruff format .
python -m ruff check . --fix
python -m ruff check .
python -m mypy factory_simulator telemetry digital_twin analytics scenario_engine optimizer backend/app ml
python -m pytest -q
```

## Frontend

See `frontend/DEPENDENCY_LOCK_STATUS.md`. The v7 ESLint configuration adds the exact pinned `typescript-eslint==8.24.0` npm package so TS/TSX is parsed with TypeScript-aware recommended rules. npm registry resolution failed with `EAI_AGAIN`, so no fake `package-lock.json` is included. The Dockerfile remains lockfile-aware and will use `npm ci` automatically once a genuine lockfile exists.
