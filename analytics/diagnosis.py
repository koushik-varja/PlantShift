from __future__ import annotations

from typing import Any


def diagnose(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    queues = metrics["average_queue_lengths"]
    machines = metrics["machines"]
    rows: list[dict[str, Any]] = []
    stage_to_machine = {value["stage"]: (machine_id, value) for machine_id, value in machines.items()}

    for stage in ("A", "B", "C", "D"):
        machine_id, machine = stage_to_machine[stage]
        upstream_queue = 0.0 if stage == "A" else float(queues.get(stage, 0.0))
        utilization = float(machine["utilization"])
        downtime = float(machine["unplanned_downtime_min"])
        score = min(
            1.0,
            0.58 * utilization + 0.24 * min(upstream_queue / 10.0, 1.0) + 0.18 * min(downtime / 30.0, 1.0),
        )
        confidence = "HIGH" if score >= 0.75 else "MEDIUM" if score >= 0.52 else "LOW"
        rows.append(
            {
                "machine_id": machine_id,
                "stage": stage,
                "utilization": utilization,
                "average_input_queue": upstream_queue,
                "unplanned_downtime_min": downtime,
                "blocked_min": float(machine["blocked_min"]),
                "bottleneck_score": round(score, 4),
                "likely_bottleneck": confidence,
                "evidence": [
                    f"utilization={utilization:.1%}",
                    f"avg input queue={upstream_queue:.2f}",
                    f"unplanned downtime={downtime:.1f} min",
                ],
            }
        )

    rows.sort(key=lambda row: row["bottleneck_score"], reverse=True)
    if metrics["scrap_rate"] > 0.03:
        rows.append(
            {
                "type": "quality_loss",
                "severity": "MEDIUM",
                "evidence": [
                    f"scrap rate={metrics['scrap_rate']:.1%}",
                    f"rework units={metrics['rework_units']}",
                ],
            }
        )
    if metrics["late_orders"] > 0:
        rows.append(
            {
                "type": "schedule_reliability",
                "severity": ("HIGH" if metrics["late_orders"] > metrics["throughput_units"] * 0.2 else "MEDIUM"),
                "evidence": [
                    f"late orders={metrics['late_orders']}",
                    f"mean lead time={metrics['lead_time_mean_min']} min",
                ],
            }
        )
    return rows
