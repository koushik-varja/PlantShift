from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MachineState(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    MAINTENANCE = "MAINTENANCE"
    FAILED = "FAILED"
    OFFLINE = "OFFLINE"


class MaintenanceStrategy(StrEnum):
    NONE = "NONE"
    MAINTENANCE_NOW = "MAINTENANCE_NOW"
    NEXT_SHIFT = "NEXT_SHIFT"
    LOW_DEMAND_WINDOW = "LOW_DEMAND_WINDOW"
    RUN_TO_FAILURE = "RUN_TO_FAILURE"
    CONDITION_TRIGGERED = "CONDITION_TRIGGERED"


@dataclass(slots=True)
class DemandPeriod:
    start_min: float
    end_min: float
    multiplier: float
    label: str


@dataclass(slots=True)
class MachineConfig:
    machine_id: str
    name: str
    process: str
    cycle_time_min: float
    base_failure_probability: float
    mttr_min: float
    wear_per_cycle: float
    base_kw: float
    nominal_rpm: float
    capacity: int = 1


@dataclass(slots=True)
class Job:
    job_id: str
    created_at_min: float
    due_at_min: float
    priority: int
    defective: bool = False
    quality_missed: bool = False


@dataclass(slots=True)
class MachineStats:
    cycles: int = 0
    busy_min: float = 0.0
    planned_downtime_min: float = 0.0
    unplanned_downtime_min: float = 0.0
    blocked_min: float = 0.0
    failures: int = 0
    maintenance_events: int = 0
    energy_kwh: float = 0.0


@dataclass(slots=True)
class ServerState:
    server_id: str
    wear: float = 0.08
    state: MachineState = MachineState.IDLE
    current_job: Job | None = None
    blocked_since: float | None = None
    pending_after_repair: bool = False
    scheduled_maintenance_done: bool = False
    pending_maintenance: bool = False
    # Bounded recent observable condition samples used by the transparent CBM policy.
    # Hidden wear remains simulator physics/ground truth and is not a decision input.
    condition_history: list[dict[str, float]] = field(default_factory=list)


@dataclass(slots=True)
class FactoryConfig:
    duration_hours: float = 8.0
    demand_per_hour: float = 15.0
    target_lead_time_min: float = 75.0
    buffer_sizes: dict[str, int] = field(default_factory=lambda: {"A": 24, "B": 18, "C": 16, "Q": 14, "D": 18})
    machines: dict[str, MachineConfig] = field(default_factory=dict)
    inspection_delay_min: float = 1.8
    inspection_accuracy: float = 0.94
    defect_detection_rate: float = 0.86
    rework_success_rate: float = 0.72
    rework_delay_min: float = 5.0
    scrap_if_detected_failure: bool = True
    scheduling_rule: str = "fifo"
    cbm_enabled: bool = False
    cbm_threshold: float = 0.72
    cbm_stages: tuple[str, ...] = ("A", "B", "C", "D")
    planned_maintenance_min: float = 12.0
    maintenance_strategy: MaintenanceStrategy = MaintenanceStrategy.NONE
    maintenance_stage: str = "B"
    maintenance_start_min: float | None = None
    iot_visibility: float = 0.0
    speed_multipliers: dict[str, float] = field(default_factory=dict)
    demand_periods: tuple[DemandPeriod, ...] = (
        DemandPeriod(0.0, 480.0, 1.20, "HIGH"),
        DemandPeriod(480.0, 960.0, 1.00, "MEDIUM"),
        DemandPeriod(960.0, 1440.0, 0.60, "LOW"),
    )


def baseline_config(duration_hours: float = 8.0) -> FactoryConfig:
    machines = {
        "A": MachineConfig("machineA", "Legacy Machine A", "Cutting", 3.1, 0.007, 18.0, 0.010, 6.0, 1600),
        "B": MachineConfig("machineB", "Legacy Machine B", "Processing", 4.0, 0.012, 24.0, 0.014, 8.5, 1400),
        "C": MachineConfig("machineC", "PLC Machine C", "Assembly", 3.4, 0.006, 15.0, 0.009, 7.0, 1500),
        "D": MachineConfig("machineD", "Legacy Machine D", "Packaging", 2.7, 0.005, 14.0, 0.008, 5.0, 1350),
    }
    return FactoryConfig(duration_hours=duration_hours, machines=machines)
