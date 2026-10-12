from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Stage = Literal["A", "B", "C", "D"]
MaintenanceStrategy = Literal[
    "MAINTENANCE_NOW",
    "NEXT_SHIFT",
    "LOW_DEMAND_WINDOW",
]
SchedulingStrategy = Literal["fifo", "edd", "weighted_priority"]


class ScenarioParameters(BaseModel):
    iot_visibility: float | None = Field(default=None, ge=0, le=1)
    central_visibility: float | None = Field(default=None, ge=0, le=1)
    cbm_threshold: float | None = Field(default=None, ge=0.1, le=0.95)
    maintenance_stage: Stage | None = None
    maintenance_strategy: MaintenanceStrategy | None = None
    planned_maintenance_min: float | None = Field(default=None, gt=0, le=240)
    maintenance_start_min: float | None = Field(default=None, ge=0, le=1440)
    scheduling_rule: SchedulingStrategy | None = None
    buffer_b: int | None = Field(default=None, ge=1, le=500)
    buffer_c: int | None = Field(default=None, ge=1, le=500)
    capacity_stage: Stage | None = None
    capacity_count: int | None = Field(default=None, ge=1, le=5)
    speed_multiplier: float | None = Field(default=None, ge=0.6, le=2)
    inspection_delay_min: float | None = Field(default=None, gt=0, le=30)
    inspection_accuracy: float | None = Field(default=None, ge=0, le=1)
    defect_detection_rate: float | None = Field(default=None, ge=0, le=1)
    energy_factor: float | None = Field(default=None, ge=0.5, le=1.2)


class ScenarioRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    interventions: list[str] = Field(default_factory=list, max_length=12)
    duration_hours: float = Field(default=24, gt=0, le=72)
    seed: int = Field(default=7, ge=0, le=2_000_000_000)
    parameters: ScenarioParameters = Field(default_factory=ScenarioParameters)
    cost_overrides: dict[str, float] = Field(default_factory=dict)
    effort_overrides: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_overrides(self):
        if any(value < 0 for value in self.cost_overrides.values()):
            raise ValueError("cost overrides must be non-negative")
        if any(value < 1 or value > 100 for value in self.effort_overrides.values()):
            raise ValueError("effort overrides must be in [1,100]")
        return self


class MonteCarloRequest(ScenarioRequest):
    runs: int = Field(default=12, ge=3, le=100)


Objective = Literal[
    "MAXIMIZE_THROUGHPUT",
    "MAXIMIZE_OEE",
    "MINIMIZE_DOWNTIME",
    "MINIMIZE_SCRAP",
    "MINIMIZE_ENERGY",
    "MINIMIZE_LATE_ORDERS",
    "MAXIMIZE_ESTIMATED_VALUE",
    "MAXIMIZE_BENEFIT_PER_EFFORT",
    "BALANCED_OPERATIONAL_IMPACT",
    "BALANCED",
]


class PortfolioBusinessAssumptions(BaseModel):
    value_per_finished_unit: float = Field(default=80, ge=0)
    downtime_cost_per_hour: float = Field(default=200, ge=0)
    scrap_cost_per_unit: float = Field(default=55, ge=0)
    rework_cost_per_unit: float = Field(default=18, ge=0)
    energy_cost_per_kwh: float = Field(default=0.12, ge=0)
    planned_maintenance_cost: float = Field(default=90, ge=0)
    unplanned_maintenance_cost: float = Field(default=220, ge=0)


class PortfolioRequest(BaseModel):
    budget: float = Field(default=100, ge=0, le=100000)
    implementation_capacity: int = Field(default=10, ge=1, le=100)
    maximum_risk: int = Field(default=8, ge=0, le=100)
    objective: Objective = "MAXIMIZE_BENEFIT_PER_EFFORT"
    duration_hours: float = Field(default=24, gt=0, le=72)
    evaluation_runs: int = Field(default=5, ge=3, le=20)
    weights: dict[str, float] = Field(default_factory=dict)
    cost_overrides: dict[str, float] = Field(default_factory=dict)
    effort_overrides: dict[str, int] = Field(default_factory=dict)
    business_assumptions: PortfolioBusinessAssumptions = Field(default_factory=PortfolioBusinessAssumptions)
    scenario_parameters: ScenarioParameters = Field(default_factory=ScenarioParameters)

    @model_validator(mode="after")
    def validate_values(self):
        allowed = {"throughput", "oee", "downtime", "scrap", "energy", "late_orders"}
        if any(key not in allowed or value < 0 for key, value in self.weights.items()):
            raise ValueError("weights must be non-negative known objective components")
        if any(value < 0 for value in self.cost_overrides.values()):
            raise ValueError("cost overrides must be non-negative")
        if any(value < 1 or value > 100 for value in self.effort_overrides.values()):
            raise ValueError("effort overrides must be in [1,100]")
        return self


class RoadmapRequest(BaseModel):
    interventions: list[str] = Field(default_factory=list, max_length=12)
    max_effort_per_phase: int | None = Field(default=None, ge=1, le=100)
    max_cost_per_phase: float | None = Field(default=None, gt=0, le=100000)
    cost_overrides: dict[str, float] = Field(default_factory=dict)
    effort_overrides: dict[str, int] = Field(default_factory=dict)


class MaintenanceWindowRequest(BaseModel):
    stage: Stage = "B"
    duration_hours: float = Field(default=24, gt=0, le=72)
    seed: int = Field(default=17, ge=0)
    planned_duration_min: float = Field(default=30, gt=0, le=240)


class BusinessValueRequest(BaseModel):
    scenario: ScenarioRequest
    value_per_finished_unit: float = Field(default=80, ge=0)
    downtime_cost_per_hour: float = Field(default=200, ge=0)
    scrap_cost_per_unit: float = Field(default=55, ge=0)
    rework_cost_per_unit: float = Field(default=18, ge=0)
    energy_cost_per_kwh: float = Field(default=0.12, ge=0)
    planned_maintenance_cost: float = Field(default=90, ge=0)
    unplanned_maintenance_cost: float = Field(default=220, ge=0)


class SensitivityRequest(BaseModel):
    scenarios: list[ScenarioRequest] = Field(min_length=2, max_length=8)
    value_per_finished_unit: float = Field(default=80, ge=0)
    downtime_cost_per_hour: float = Field(default=200, ge=0)
    scrap_cost_per_unit: float = Field(default=55, ge=0)
    rework_cost_per_unit: float = Field(default=18, ge=0)
    energy_cost_per_kwh: float = Field(default=0.12, ge=0)
    planned_maintenance_cost: float = Field(default=90, ge=0)
    unplanned_maintenance_cost: float = Field(default=220, ge=0)
