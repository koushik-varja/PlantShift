from __future__ import annotations

from typing import Any

from scenario_engine import CATALOG


def build_roadmap(
    interventions: list[str],
    *,
    max_effort_per_phase: int | None = None,
    max_cost_per_phase: float | None = None,
    cost_overrides: dict[str, float] | None = None,
    effort_overrides: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    selected = set(interventions)
    unknown = selected - CATALOG.keys()
    if unknown:
        raise ValueError(f"unknown interventions: {sorted(unknown)}")

    # A requested roadmap must be self-contained: prerequisites have to be selected,
    # not silently invented.
    for item in selected:
        missing = set(CATALOG[item].prerequisites) - selected
        if missing:
            raise ValueError(f"{item} requires {sorted(missing)}")

    costs = cost_overrides or {}
    efforts = effort_overrides or {}
    completed: set[str] = set()
    phases = []
    phase = 1

    while completed != selected:
        ready = sorted(item for item in selected - completed if set(CATALOG[item].prerequisites).issubset(completed))
        if not ready:
            raise ValueError("intervention dependency cycle")

        chosen: list[str] = []
        used_effort = 0
        used_cost = 0.0
        for item in ready:
            effort = int(efforts.get(item, CATALOG[item].implementation_effort))
            cost = float(costs.get(item, CATALOG[item].illustrative_cost))
            if max_effort_per_phase is not None and effort > max_effort_per_phase:
                raise ValueError(f"{item} exceeds max effort per phase")
            if max_cost_per_phase is not None and cost > max_cost_per_phase:
                raise ValueError(f"{item} exceeds max cost per phase")
            if chosen and (
                (max_effort_per_phase is not None and used_effort + effort > max_effort_per_phase)
                or (max_cost_per_phase is not None and used_cost + cost > max_cost_per_phase)
            ):
                continue
            chosen.append(item)
            used_effort += effort
            used_cost += cost

        if not chosen:
            raise ValueError("phase constraints leave no feasible intervention")
        phases.append(
            {
                "phase": phase,
                "interventions": chosen,
                "rationale": ("Only selected interventions whose actual prerequisites are already complete are scheduled in this wave."),
                "illustrative_cost": round(used_cost, 2),
                "implementation_effort": used_effort,
            }
        )
        completed.update(chosen)
        phase += 1
    return phases
