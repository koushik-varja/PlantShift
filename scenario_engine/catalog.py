from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Intervention:
    id: str
    name: str
    description: str
    technical_requirements: tuple[str, ...]
    implementation_effort: int
    illustrative_cost: float
    risk: int
    prerequisites: tuple[str, ...]
    affected_parameters: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("technical_requirements", "prerequisites", "affected_parameters"):
            data[key] = list(data[key])
        data["cost_label"] = "ILLUSTRATIVE / USER-CONFIGURABLE"
        return data


CATALOG: dict[str, Intervention] = {
    "iot_retrofit": Intervention(
        "iot_retrofit",
        "IoT retrofit",
        "Adds edge sensing and machine visibility; does not directly increase production capacity.",
        ("edge sensors", "edge adapter", "MQTT"),
        2,
        18.0,
        1,
        (),
        ("iot_visibility", "diagnostic_delay"),
    ),
    "telemetry_platform": Intervention(
        "telemetry_platform",
        "Centralized telemetry platform",
        "Normalizes plant events and maintains recent operational state.",
        ("MQTT broker", "ingestion service", "database"),
        2,
        14.0,
        1,
        ("iot_retrofit",),
        ("telemetry_history",),
    ),
    "condition_maintenance": Intervention(
        "condition_maintenance",
        "Condition-based maintenance",
        "Uses recent observable sensor condition signals to schedule maintenance before likely failures.",
        ("telemetry history", "transparent condition policy"),
        3,
        25.0,
        2,
        ("iot_retrofit", "telemetry_platform"),
        ("cbm_enabled", "planned_maintenance"),
    ),
    "optimized_scheduling": Intervention(
        "optimized_scheduling",
        "Improved production scheduling",
        "Prioritizes jobs using due-date and priority information.",
        ("digital order queue",),
        2,
        12.0,
        1,
        (),
        ("scheduling_rule",),
    ),
    "buffer_redesign": Intervention(
        "buffer_redesign",
        "Buffer redesign",
        "Changes selected queue capacities to reduce blocking or excessive WIP.",
        ("process-flow study",),
        2,
        10.0,
        1,
        (),
        ("buffer_sizes",),
    ),
    "capacity_addition": Intervention(
        "capacity_addition",
        "Additional processing capacity",
        "Adds a parallel processing resource at the constrained stage.",
        ("space", "operator/automation capacity"),
        4,
        42.0,
        3,
        (),
        ("machine_capacity",),
    ),
    "quality_assist": Intervention(
        "quality_assist",
        "Assisted quality inspection",
        "Models faster and more accurate defect detection without claiming a deployed CV system.",
        ("inspection instrumentation",),
        3,
        22.0,
        2,
        (),
        ("inspection_delay", "defect_detection_rate"),
    ),
    "maintenance_window": Intervention(
        "maintenance_window",
        "Maintenance-window optimization",
        "Moves planned work to lower-impact windows and reduces avoidable diagnostic delay.",
        ("maintenance plan", "demand calendar"),
        2,
        9.0,
        1,
        ("iot_retrofit",),
        ("planned_maintenance_min",),
    ),
    "energy_efficiency": Intervention(
        "energy_efficiency",
        "Energy-efficiency intervention",
        "Reduces modeled energy intensity without changing nominal production speed.",
        ("drive/process tuning",),
        2,
        11.0,
        1,
        (),
        ("energy_intensity",),
    ),
}
