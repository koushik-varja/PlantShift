from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TelemetryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=8, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    machine_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    stage: str = Field(pattern=r"^[A-D]$")
    timestamp: datetime
    sim_minute: float = Field(ge=0)
    state: str
    vibration_mm_s: float = Field(ge=0, le=100)
    temperature_c: float = Field(ge=-50, le=300)
    load: float = Field(ge=0, le=2)
    rpm: float = Field(ge=0, le=100000)
    energy_kw: float = Field(ge=0, le=10000)
    wear: float | None = Field(
        default=None,
        ge=0,
        le=1.2,
        description="Synthetic simulator ground truth; never a deployed ML feature",
    )
    cycle_id: str | None = None
    failure_event: bool = False
    production_context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_tz_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must include timezone")
        return value
