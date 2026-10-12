# Surgical upgrade audit matrix

This matrix records the major weaknesses found in the supplied PlantShift repository and the action taken without replacing the working project architecture.

| Area | Prior weakness | Upgrade |
|---|---|---|
| Maintenance | Strategy approximated with parameter changes | Explicit timed maintenance events and configurable demand periods |
| Runtime ML | Offline evaluation only | Startup-loaded inference service, health API, twin integration, SSE |
| ML features | Hidden simulator wear used as feature | Observable telemetry only; wear retained only as synthetic ground truth |
| Rolling features | Machine-only grouping | `run_id` + `machine_id`, chronological grouping |
| Portfolio scoring | Single stochastic run | Paired deterministic seeds with median/P10/P90 deltas |
| Objectives | Limited/fixed scoring | Nine objectives plus validated configurable BALANCED weights |
| Energy | Weak decision role | Energy, energy/unit and energy cost in scenarios/value/optimizer |
| Costs | Source-code defaults only | API/UI cost and effort overrides; defaults labeled illustrative |
| Business value | Partial | Transparent observed/simulated/estimated separation and formulas |
| Sensitivity | Limited | Multi-assumption stability testing and winner frequency |
| Central telemetry | Potential direct benefit | Visibility/detection-delay enabler only; no arbitrary throughput boost |
| Brownfield edge | Near passthrough | Multiple legacy schemas, conversions, validation, canonical normalization |
| Idempotency | In-memory only | Persistent globally keyed processed-event ledger |
| Bridge failure | Immediate loss | Bounded batching, retries/backoff, DLQ, counters |
| Late telemetry | Could regress state | Persist historically; never overwrite a newer twin state |
| Intervention params | Loose dictionaries at boundary | Validated Pydantic parameter model and enums/ranges |
| Live UI | One-shot state | SSE stream, EventSource reconnect/cleanup |
| Frontend | Compressed/raw JSON-heavy | Typed decision-support pages and tables/controls; same React/Vite app |
| Roadmap | Weak sequencing | Real prerequisite graph plus wave cost/effort constraints |
| Benchmarks | In-process metric overclaimed | Honest microbenchmark label + separate executable E2E benchmark |
| DB writes | Per-event transactions | Batch transaction path with race-safe idempotency handling |
| Tests | 16 tests | Expanded behavioral/acceptance suite; final count in verification report |
| Dependencies | Floating versions/images | Direct Python/frontend dependency pins and pinned container images |

## Final-v2 patch additions

| Area | Final issue | Final-v2 action |
|---|---|---|
| Maintenance horizon | 8h UI could select a 16h low-demand window that never ran | Backend rejects any fixed maintenance start at/outside the horizon; UI exposes 8/16/24/48/72h and shows the window/validation |
| Estimated-value objective | Name implied financial value but score was an operational heuristic | Uses paired-seed business-value components and median estimated net value after illustrative implementation cost |
| Operational composite | Financial and KPI semantics were conflated | `BALANCED_OPERATIONAL_IMPACT` is explicit; legacy `BALANCED` remains an API alias |
| Optimizer explanation | One score hid trade-offs | Returns SIMULATED robust operational deltas plus ESTIMATED P10/median/P90 financial components |
| Reproducibility | Missing npm/uv locks | Real resolver attempts documented; no fabricated lock files when registry/cache is unavailable |
