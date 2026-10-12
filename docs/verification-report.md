# Verification report — PlantShift final-v7 tooling quality gate

Build date: 2026-10-12.

This v7 patch is tooling/code-quality cleanup only. The validated v6 product,
architecture, algorithms, API behavior, and frontend functionality are preserved.
Detailed v6 integration verification remains in
`docs/final-integration-freeze-v6-report.md`.

## MEASURED checks completed

- `python -m pytest -o addopts='' -q`: **67 passed, 0 failed**.
- `python -m compileall -q factory_simulator telemetry digital_twin analytics scenario_engine optimizer backend/app ml tests`: **PASS**.
- `python -m scripts.smoke`: **PASS**.
- `node --check frontend/eslint.config.js`: **PASS** (JavaScript config syntax only; not an ESLint lint run).

## Python code-quality cleanup

Remaining compressed/semicolon-heavy test code and dense Python formatting were
cleaned without changing intended behavior. `tests/test_upgrade_acceptance.py`
was fully reformatted, and touched Python source was normalized for import
organization, explicit `zip(strict=...)` intent, modern `collections.abc` imports,
and configured 140-column formatting. A local AST scan found no unused imports in
non-`__init__.py` modules after cleanup.

The configured Ruff selection remains `E`, `F`, `I`, `B`, `UP`; it was not
weakened.

### Ruff status

**NOT EXECUTED**. Ruff is not installed, is absent from the local uv cache, and
Python registry resolution is unavailable. No Ruff pass is claimed.

Local command when dependencies are available:

```bash
python -m ruff format .
python -m ruff check . --fix
python -m ruff check .
python -m pytest -q
```

## TypeScript ESLint configuration

The frontend now uses a TypeScript-aware ESLint 9 flat configuration with exact
`typescript-eslint` version `8.24.0`. The configuration applies TypeScript
recommended parsing/rules to TS/TSX, keeps React hooks/refresh rules, and does not
apply core JavaScript `no-undef` to TypeScript files.

The version is compatible by declared peer ranges with the repository's ESLint
9.20.1 and TypeScript 5.7.3. Package installation itself could not be resolved in
this sandbox.

## Frontend dependency / lock / quality-gate status

A genuine npm dependency resolution attempt failed with `EAI_AGAIN` against
`registry.npmjs.org`. No `package-lock.json` is fabricated.

Without `node_modules`:

- `npm run lint`: executable unavailable (`eslint: not found`).
- `npm test`: executable unavailable (`vitest: not found`).
- `npm run build`: fails because `vite/client` type definitions are unavailable.

Therefore frontend lint/test/build status is **NOT VERIFIED** here.

On a network-enabled machine:

```bash
cd frontend
npm install
npm ci
npm run lint
npm test
npm run build
```

## mypy status

**NOT EXECUTED**. `python -m mypy` is unavailable and `uvx --offline
mypy==1.18.2` cannot resolve it from cache. No mypy success is claimed.

Local command:

```bash
python -m mypy factory_simulator telemetry digital_twin analytics scenario_engine optimizer backend/app ml
```

## Lockfiles

All direct dependency versions remain exactly pinned. No frontend lockfile or new
Python lockfile was hand-written when resolver access was unavailable.

See `docs/final-tooling-quality-gate-v7-report.md`,
`docs/dependency-lock-status.md`, and `frontend/DEPENDENCY_LOCK_STATUS.md` for
reproduction commands and exact environment limitations.
