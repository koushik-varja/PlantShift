# Design decisions

- **Preserve the original event-calendar simulator.** It is small enough to audit and deterministic under seeds; adding SimPy solely as a keyword would not improve correctness.
- **Exhaustively enumerate nine interventions.** The search space is small and explainable. Robustness comes from paired multi-seed evaluation, not from replacing a transparent algorithm with a heavier optimizer.
- **Separate global idempotency from Timescale uniqueness.** Timescale unique indexes must include the time partition column. A small `processed_event_ids(event_id PK)` ledger gives restart-safe global idempotency while telemetry remains time-partitionable.
- **Keep simulator wear out of decisions that claim deployability.** Hidden degradation is simulator physics / synthetic ground truth only. Runtime ML uses observable telemetry, and simulator CBM uses a separate transparent bounded observable-sensor condition score.
- **Use SSE for live twins.** The dashboard is server→browser streaming only; WebSockets would add unnecessary bidirectional complexity.
- **Batch MQTT→HTTP writes.** The bridge sends bounded batches to one DB transaction, but retains a bounded queue, retry limit, jitter and DLQ rather than building a heavyweight messaging subsystem.
- **Treat financial outputs as estimates.** Business assumptions are configurable and formulas are transparent; no vendor quote or guaranteed ROI is implied.

- **Split ML by complete simulation run.** Chronological run ordering is retained, but train/validation/test boundaries are applied to whole `run_id` groups so one synthetic run cannot cross partitions.
- **Keep maintenance comparisons apples-to-apples.** Run-to-failure and scheduled alternatives share the same IoT visibility, horizon, seed and demand seed; only the maintenance policy changes.
- **Use one illustrative monetary unit.** Financial assumptions are unit-consistent and estimated net value refers to the selected simulated operating period; no guaranteed or automatically annualized ROI is claimed.
