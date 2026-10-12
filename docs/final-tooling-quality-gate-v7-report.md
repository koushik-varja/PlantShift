# PlantShift v7 — final tooling quality gate

Date: 2026-10-12

This patch is tooling/code-quality cleanup only. Product behavior, simulation,
intervention mechanics, ML methodology, telemetry semantics, MQTT batching,
retry/DLQ behavior, twin behavior, scenario/Monte Carlo logic, optimizer logic,
business-value logic, sensitivity, roadmap, API behavior, and frontend product
functionality were not intentionally changed.

## Python formatting / Ruff preparation

The remaining dense Python formatting was cleaned manually because Ruff is not
installed and cannot be resolved from the package registry in this environment.
The cleanup includes tests (especially `tests/test_upgrade_acceptance.py`) and
remaining long/dense source literals/imports. The configured Ruff rules remain:

```toml
select = ["E", "F", "I", "B", "UP"]
```

No Ruff rule was weakened. Additional Ruff-sensitive cleanup includes:

- removed unused imports discovered by an AST scan;
- normalized import grouping/order in touched files;
- moved `Callable` / `Iterable` imports to `collections.abc`;
- made `zip(..., strict=...)` intent explicit where appropriate;
- removed semicolon-packed statements;
- removed Python source lines longer than the configured 140-column limit.

Actual Ruff execution status: **NOT EXECUTED**.

Attempts/checks:

```text
python -m ruff --version -> No module named ruff
uvx --offline ruff==0.14.1 --version -> ruff not present in cache
pip install ruff==0.14.1 mypy==1.18.2 -> registry resolution unavailable
```

Exact local gate once registry access is available:

```bash
python -m ruff format .
python -m ruff check . --fix
python -m ruff check .
python -m pytest -q
```

## Backend regression

Executed after the final formatting/config changes:

```text
python -m pytest -o addopts='' -q
67 passed in 18.48s
```

Also executed:

```text
python -m compileall -q factory_simulator telemetry digital_twin analytics scenario_engine optimizer backend/app ml tests
PASS

python -m scripts.smoke
PASS
```

This preserves the v6 67-test backend baseline.

## TypeScript-aware ESLint configuration

`frontend/eslint.config.js` now uses the ESLint 9 flat-config approach with the
`typescript-eslint` package instead of applying plain JavaScript parsing/rules
directly to TS/TSX.

Pinned addition:

```json
"typescript-eslint": "8.24.0"
```

That release declares peer compatibility with ESLint `^8.57.0 || ^9.0.0` and
TypeScript `>=4.8.4 <5.8.0`, covering this repository's ESLint 9.20.1 and
TypeScript 5.7.3.

The config applies TypeScript recommended rules to TS/TSX and explicitly disables
core JavaScript `no-undef` for TypeScript files, where TypeScript performs the
corresponding name/type checking. React hooks and React refresh rules remain
active for `src/**/*.ts` and `src/**/*.tsx`.

`node --check frontend/eslint.config.js`: **PASS** (syntax only).

## Frontend install / lint / test / build

The npm registry is unavailable from this environment. A real install attempt
failed with `EAI_AGAIN` resolving `registry.npmjs.org`. Therefore no
`package-lock.json` was fabricated and there is no claim that the dependency-based
frontend quality gate passed.

Observed follow-up commands without installed dependencies:

```text
npm run lint  -> exit 127, eslint executable unavailable
npm test      -> exit 127, vitest executable unavailable
npm run build -> TS2688, vite/client type definitions unavailable
```

Status: **NOT VERIFIED / NOT EXECUTABLE WITH MISSING DEPENDENCIES**.

On a network-enabled machine:

```bash
cd frontend
npm install
npm ci
npm run lint
npm test
npm run build
```

Keep the resolver-generated `package-lock.json`; do not hand-write it.

## mypy

Actual mypy execution status: **NOT EXECUTED**.

```text
python -m mypy --version -> No module named mypy
uvx --offline mypy==1.18.2 --version -> mypy not present in cache
```

Exact local type gate:

```bash
python -m mypy factory_simulator telemetry digital_twin analytics scenario_engine optimizer backend/app ml
```

No global mypy disable or broad new `type: ignore` comments were added for this
patch.

## Final status

- Backend regression: **67 passed, 0 failed**.
- Python compile/smoke: **PASS**.
- Ruff: **NOT EXECUTED** (tool unavailable).
- mypy: **NOT EXECUTED** (tool unavailable).
- ESLint config source: **UPDATED + syntax checked**.
- npm lint/test/build: **NOT VERIFIED** because dependency resolution is unavailable.
- `package-lock.json`: **not fabricated**.
