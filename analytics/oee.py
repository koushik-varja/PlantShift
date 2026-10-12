from __future__ import annotations


def calculate_oee(
    planned_time: float,
    downtime: float,
    ideal_cycle_time: float,
    total_count: int,
    good_count: int,
    operating_time: float,
) -> dict[str, float]:
    if planned_time <= 0 or operating_time < 0 or total_count < 0 or good_count < 0 or good_count > total_count:
        raise ValueError("invalid OEE inputs")

    availability = max(0.0, min(1.0, (planned_time - downtime) / planned_time))
    performance = 0.0 if operating_time == 0 else max(0.0, min(1.0, ideal_cycle_time * total_count / operating_time))
    quality = 0.0 if total_count == 0 else good_count / total_count
    return {
        "availability": availability,
        "performance": performance,
        "quality": quality,
        "oee": availability * performance * quality,
    }
