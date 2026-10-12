# Transformation methodology

PlantShift follows a repeatable decision sequence:

1. **Observe current state.** Run the synthetic brownfield line and calculate OEE, flow, downtime, quality, lateness and energy metrics.
2. **Diagnose evidence.** Rank likely bottlenecks and surface quality/scheduling losses from simulation evidence rather than an LLM.
3. **Configure interventions.** Select transformations and optionally override illustrative cost, effort and typed operational parameters.
4. **Run counterfactuals.** Baseline and transformed cases reuse the same demand profile and seed for comparability.
5. **Quantify uncertainty.** Paired Monte Carlo runs report median/P10/P90 deltas rather than one lucky seed.
6. **Optimize a feasible portfolio.** Exhaustive enumeration enforces budget, effort, risk and prerequisite constraints, then scores robust deltas under a user-selected objective.
7. **Estimate business effect.** Transparent assumptions convert only supported simulated effects into illustrative financial impact.
8. **Test stability.** Vary high-impact assumptions and measure how often the preferred candidate remains preferred.
9. **Phase the roadmap.** Topological prerequisite ordering is combined with optional per-wave cost/effort capacity; independent interventions are not given invented dependencies.

All scenario/optimizer outputs remain SIMULATED. Financial outputs remain ESTIMATED / ILLUSTRATIVE.
