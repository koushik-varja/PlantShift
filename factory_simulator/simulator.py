from __future__ import annotations

import heapq
import random
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from .models import FactoryConfig, Job, MachineState, MachineStats, MaintenanceStrategy, ServerState, baseline_config


@dataclass(order=True, slots=True)
class Event:
    at: float
    sequence: int
    kind: str
    stage: str = ""
    server_idx: int = -1
    job: Job | None = None


TelemetrySink = Callable[[dict[str, Any]], None]


class FactorySimulator:
    """Original event-calendar simulator for a defendable student-scale brownfield line."""

    stages = ("A", "B", "C", "Q", "D")
    machine_stages = ("A", "B", "C", "D")

    def __init__(
        self,
        config: FactoryConfig | None = None,
        *,
        seed: int = 7,
        demand_seed: int = 2026,
        telemetry_sink: TelemetrySink | None = None,
        run_id: str | None = None,
    ) -> None:
        self.config = config or baseline_config()
        self.seed = seed
        self.demand_seed = demand_seed
        self.rng = random.Random(seed)
        self.demand_rng = random.Random(demand_seed)
        self.telemetry_sink = telemetry_sink
        self.run_id = run_id or f"run-{seed}"
        self.now = 0.0
        self._seq = 0
        self.events: list[Event] = []
        self.queues: dict[str, list[Job]] = {s: [] for s in self.stages}
        self.queue_history: list[tuple[float, dict[str, int]]] = [(0.0, {s: 0 for s in self.stages})]
        self.servers: dict[str, list[ServerState]] = {}
        self.stats: dict[str, MachineStats] = {s: MachineStats() for s in self.machine_stages}
        self.created = 0
        self.finished = 0
        self.scrap = 0
        self.defects_generated = 0
        self.defects_detected = 0
        self.defects_missed = 0
        self.rework = 0
        self.false_positive_inspections = 0
        self.late_orders = 0
        self.lead_times: list[float] = []
        self.telemetry: list[dict[str, Any]] = []
        self.overflow_events = 0
        self.base_time = datetime(2026, 1, 1, 6, 0, tzinfo=UTC) + timedelta(days=seed)
        for stage in self.machine_stages:
            cap = self.config.machines[stage].capacity
            self.servers[stage] = [ServerState(f"{stage}-{i + 1}") for i in range(cap)]
        self.servers["Q"] = [ServerState("Q-1")]
        self._schedule_configured_maintenance()

    def _schedule_configured_maintenance(self) -> None:
        strategy = self.config.maintenance_strategy
        if strategy in {MaintenanceStrategy.NONE, MaintenanceStrategy.RUN_TO_FAILURE, MaintenanceStrategy.CONDITION_TRIGGERED}:
            return
        if self.config.maintenance_start_min is not None:
            start = self.config.maintenance_start_min
        elif strategy == MaintenanceStrategy.MAINTENANCE_NOW:
            start = 0.0
        elif strategy == MaintenanceStrategy.NEXT_SHIFT:
            start = 480.0
        else:
            low = [p.start_min for p in self.config.demand_periods if p.label.upper() == "LOW"]
            start = low[0] if low else 960.0
        if 0.0 <= start < self.config.duration_hours * 60.0 and self.config.maintenance_stage in self.machine_stages:
            self._schedule(start, "planned_maintenance_start", self.config.maintenance_stage, 0)

    def _demand_multiplier(self, minute: float) -> float:
        minute_of_day = minute % 1440.0
        for period in self.config.demand_periods:
            if period.start_min <= minute_of_day < period.end_min:
                return max(0.05, period.multiplier)
        return 1.0

    def _begin_planned_maintenance(self, stage: str, server_idx: int) -> None:
        server = self.servers[stage][server_idx]
        if server.scheduled_maintenance_done:
            return
        if server.current_job is not None:
            server.pending_maintenance = True
            return
        server.state = MachineState.MAINTENANCE
        server.scheduled_maintenance_done = True
        self.stats[stage].maintenance_events += 1
        self.stats[stage].planned_downtime_min += self.config.planned_maintenance_min
        self._emit(stage, server, MachineState.MAINTENANCE, None)
        self._schedule(self.now + self.config.planned_maintenance_min, "scheduled_maintenance_done", stage, server_idx)

    def _schedule(self, at: float, kind: str, stage: str = "", server_idx: int = -1, job: Job | None = None) -> None:
        self._seq += 1
        heapq.heappush(self.events, Event(at, self._seq, kind, stage, server_idx, job))

    def _record_queues(self) -> None:
        snap = {s: len(self.queues[s]) for s in self.stages}
        if self.queue_history[-1][1] != snap:
            self.queue_history.append((self.now, snap))

    def _queue_capacity(self, stage: str) -> int:
        return max(1, int(self.config.buffer_sizes.get(stage, 9999)))

    def _can_accept(self, stage: str) -> bool:
        return len(self.queues[stage]) < self._queue_capacity(stage)

    def _enqueue(self, stage: str, job: Job) -> bool:
        if not self._can_accept(stage):
            self.overflow_events += 1
            return False
        self.queues[stage].append(job)
        self._record_queues()
        self._try_start(stage)
        return True

    def _pop_job(self, stage: str) -> Job:
        q = self.queues[stage]
        if stage == "A" and self.config.scheduling_rule != "fifo":
            if self.config.scheduling_rule == "edd":
                idx = min(range(len(q)), key=lambda i: q[i].due_at_min)
            elif self.config.scheduling_rule == "weighted_priority":
                idx = min(range(len(q)), key=lambda i: (q[i].due_at_min / max(1, q[i].priority), -q[i].priority))
            else:
                idx = 0
            job = q.pop(idx)
        else:
            job = q.pop(0)
        self._record_queues()
        return job

    def _state_for_wear(self, wear: float) -> MachineState:
        return MachineState.DEGRADED if wear >= 0.62 else MachineState.RUNNING

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, value))

    def _observable_condition_score(self, stage: str, observation: dict[str, float]) -> float:
        """Transparent condition severity derived only from observable sensor values.

        Load is used both as an explicit stress term and to normalize expected
        vibration/temperature/energy. The score intentionally does not read wear.
        """
        cfg = self.config.machines[stage]
        load = float(observation["load"])
        expected_vibration = 1.15 + 0.45 * load
        expected_temperature = 42.0 + 8.0 * load
        expected_energy = cfg.base_kw * (0.25 + 0.65 * load)
        vibration_score = self._clamp01((float(observation["vibration_mm_s"]) - expected_vibration) / 3.5)
        temperature_score = self._clamp01((float(observation["temperature_c"]) - expected_temperature) / 27.0)
        rpm_score = self._clamp01((cfg.nominal_rpm - float(observation["rpm"])) / max(1.0, 0.09 * cfg.nominal_rpm))
        energy_score = self._clamp01((float(observation["energy_kw"]) - expected_energy) / max(0.1, 0.25 * cfg.base_kw))
        load_score = self._clamp01((load - 0.60) / 0.40)
        return (vibration_score + temperature_score + rpm_score + energy_score + load_score) / 5.0

    def _remember_observable_condition(self, stage: str, server: ServerState, observation: dict[str, float]) -> float:
        sample = dict(observation)
        sample["condition_score"] = self._observable_condition_score(stage, observation)
        server.condition_history.append(sample)
        del server.condition_history[:-5]
        return sample["condition_score"]

    def _condition_score(self, server: ServerState) -> float | None:
        if not server.condition_history:
            return None
        recent = server.condition_history[-3:]
        return sum(sample["condition_score"] for sample in recent) / len(recent)

    def _should_trigger_condition_maintenance(self, stage: str, server: ServerState) -> bool:
        if not self.config.cbm_enabled or stage not in self.config.cbm_stages:
            return False
        score = self._condition_score(server)
        return score is not None and score >= self.config.cbm_threshold

    def _emit(self, stage: str, server: ServerState, state: MachineState, job: Job | None, *, failure_event: bool = False) -> None:
        if stage == "Q":
            return
        cfg = self.config.machines[stage]
        wear = min(1.0, server.wear)
        load = 0.85 if state in (MachineState.RUNNING, MachineState.DEGRADED) else 0.15
        vibration = max(0.1, 1.15 + 3.5 * wear + 0.45 * load + self.rng.gauss(0, 0.10))
        temperature = 42 + 27 * wear + 8 * load + self.rng.gauss(0, 0.7)
        rpm = max(0.0, cfg.nominal_rpm * (1 - 0.09 * wear) + self.rng.gauss(0, 8)) if load > 0.5 else 0.0
        energy_kw = cfg.base_kw * (0.25 + 0.65 * load + 0.25 * wear)
        ts = self.base_time + timedelta(minutes=self.now)
        observation = {
            "vibration_mm_s": float(vibration),
            "temperature_c": float(temperature),
            "load": float(load),
            "rpm": float(rpm),
            "energy_kw": float(energy_kw),
        }
        condition_score = None
        if state in (MachineState.RUNNING, MachineState.DEGRADED):
            condition_score = self._remember_observable_condition(stage, server, observation)
        event = {
            "event_id": str(uuid4()),
            "run_id": self.run_id,
            "machine_id": cfg.machine_id,
            "stage": stage,
            "timestamp": ts.isoformat(),
            "sim_minute": round(self.now, 4),
            "state": state.value,
            "vibration_mm_s": round(vibration, 4),
            "temperature_c": round(temperature, 4),
            "load": round(load, 4),
            "rpm": round(rpm, 2),
            "energy_kw": round(energy_kw, 4),
            "wear": round(wear, 5),
            "cycle_id": job.job_id if job else None,
            "failure_event": failure_event,
            "production_context": {
                "process": cfg.process,
                "job_priority": job.priority if job else None,
                "observable_condition_score": (None if condition_score is None else round(condition_score, 5)),
            },
        }
        self.telemetry.append(event)
        if self.telemetry_sink:
            self.telemetry_sink(event)

    def _try_start(self, stage: str) -> None:
        while self.queues[stage]:
            idle_idx = next((i for i, s in enumerate(self.servers[stage]) if s.current_job is None and s.state == MachineState.IDLE), None)
            if idle_idx is None:
                return
            server = self.servers[stage][idle_idx]
            job = self._pop_job(stage)
            server.current_job = job
            if stage == "Q":
                server.state = MachineState.RUNNING
                self._schedule(self.now + self.config.inspection_delay_min, "quality_done", stage, idle_idx, job)
                continue
            self._start_machine_operation(stage, idle_idx, job)

    def _start_machine_operation(self, stage: str, server_idx: int, job: Job) -> None:
        server = self.servers[stage][server_idx]
        cfg = self.config.machines[stage]
        if self._should_trigger_condition_maintenance(stage, server):
            server.state = MachineState.MAINTENANCE
            self.stats[stage].maintenance_events += 1
            self.stats[stage].planned_downtime_min += self.config.planned_maintenance_min
            self._emit(stage, server, MachineState.MAINTENANCE, job)
            self._schedule(self.now + self.config.planned_maintenance_min, "maintenance_done", stage, server_idx, job)
            return

        failure_probability = min(0.65, cfg.base_failure_probability * 0.25 + 0.55 * max(0.0, server.wear - 0.35) ** 3)
        if self.rng.random() < failure_probability:
            server.state = MachineState.FAILED
            self.stats[stage].failures += 1
            diagnostic_delay = 6.0 * (1.0 - min(1.0, self.config.iot_visibility))
            repair = cfg.mttr_min * self.rng.uniform(0.8, 1.25) + diagnostic_delay
            self.stats[stage].unplanned_downtime_min += repair
            self._emit(stage, server, MachineState.FAILED, job, failure_event=True)
            self._schedule(self.now + repair, "repair_done", stage, server_idx, job)
            return

        state = self._state_for_wear(server.wear)
        server.state = state
        speed = max(0.6, float(self.config.speed_multipliers.get(stage, 1.0)))
        duration = cfg.cycle_time_min * (1 + 0.32 * server.wear) / speed * self.rng.uniform(0.94, 1.08)
        self.stats[stage].busy_min += duration
        self.stats[stage].energy_kwh += cfg.base_kw * (0.78 + 0.28 * server.wear) * duration / 60.0
        self._emit(stage, server, state, job)
        self._schedule(self.now + duration, "machine_done", stage, server_idx, job)

    def _upstream_of(self, stage: str) -> str | None:
        idx = self.stages.index(stage)
        return self.stages[idx - 1] if idx > 0 else None

    def _downstream_of(self, stage: str) -> str | None:
        idx = self.stages.index(stage)
        return self.stages[idx + 1] if idx + 1 < len(self.stages) else None

    def _release_server(self, stage: str, server_idx: int) -> None:
        server = self.servers[stage][server_idx]
        server.current_job = None
        server.state = MachineState.IDLE
        server.blocked_since = None
        if server.pending_maintenance:
            server.pending_maintenance = False
            self._begin_planned_maintenance(stage, server_idx)
            return
        self._try_start(stage)

    def _transfer_or_block(self, stage: str, server_idx: int, job: Job) -> None:
        downstream = self._downstream_of(stage)
        if downstream is None:
            self.finished += 1
            lead = self.now - job.created_at_min
            self.lead_times.append(lead)
            if self.now > job.due_at_min:
                self.late_orders += 1
            if job.quality_missed:
                self.defects_missed += 1
            self._release_server(stage, server_idx)
            return
        if self._enqueue(downstream, job):
            self._release_server(stage, server_idx)
            self._retry_blocked(self._upstream_of(stage))
        else:
            server = self.servers[stage][server_idx]
            server.state = MachineState.IDLE
            server.blocked_since = self.now

    def _retry_blocked(self, stage: str | None) -> None:
        if not stage:
            return
        downstream = self._downstream_of(stage)
        if downstream is None:
            return
        for idx, server in enumerate(self.servers[stage]):
            if server.current_job is not None and server.blocked_since is not None and self._can_accept(downstream):
                self.stats[stage].blocked_min += self.now - server.blocked_since
                job = server.current_job
                server.blocked_since = None
                self._enqueue(downstream, job)
                self._release_server(stage, idx)

    def _handle_machine_done(self, event: Event) -> None:
        stage = event.stage
        server = self.servers[stage][event.server_idx]
        cfg = self.config.machines[stage]
        job = event.job
        assert job is not None
        self.stats[stage].cycles += 1
        server.wear = min(1.0, server.wear + cfg.wear_per_cycle * self.rng.uniform(0.85, 1.2))
        if stage == "C":
            defect_p = min(0.38, 0.018 + 0.22 * server.wear**2)
            if self.rng.random() < defect_p:
                job.defective = True
                self.defects_generated += 1
        self._emit(stage, server, self._state_for_wear(server.wear), job)
        self._transfer_or_block(stage, event.server_idx, job)

    def _handle_quality_done(self, event: Event) -> None:
        job = event.job
        assert job is not None
        if job.defective and self.rng.random() < self.config.defect_detection_rate:
            self.defects_detected += 1
            if self.rng.random() < self.config.rework_success_rate:
                self.rework += 1
                self._schedule(self.now + self.config.rework_delay_min, "rework_done", "Q", event.server_idx, job)
                return
            self.scrap += 1
            self._release_server("Q", event.server_idx)
            self._retry_blocked("C")
            return
        if job.defective:
            job.quality_missed = True
        elif self.rng.random() > self.config.inspection_accuracy:
            self.false_positive_inspections += 1
            self._schedule(self.now + 0.5 * self.config.inspection_delay_min, "reinspect_done", "Q", event.server_idx, job)
            return
        self._transfer_or_block("Q", event.server_idx, job)
        self._retry_blocked("C")

    def _handle_rework_done(self, event: Event) -> None:
        job = event.job
        assert job is not None
        job.defective = False
        self._transfer_or_block("Q", event.server_idx, job)
        self._retry_blocked("C")

    def _handle_arrival(self, event: Event) -> None:
        job = event.job
        assert job is not None
        if event.kind == "arrival":
            self.created += 1
        if not self._enqueue("A", job):
            # External backlog retries without dropping demand.
            self._schedule(self.now + 1.0, "arrival_retry", job=job)
        self._try_start("A")

    def _generate_demand_events(self) -> None:
        horizon = self.config.duration_hours * 60.0
        t = 0.0
        idx = 0
        while t < horizon:
            effective_rate = max(0.1, self.config.demand_per_hour * self._demand_multiplier(t))
            mean_interarrival = 60.0 / effective_rate
            jitter = self.demand_rng.uniform(0.75, 1.25)
            t += mean_interarrival * jitter
            if t >= horizon:
                break
            idx += 1
            priority = self.demand_rng.choices([1, 2, 3], weights=[0.62, 0.28, 0.10], k=1)[0]
            due = t + self.config.target_lead_time_min / (1 + 0.12 * (priority - 1))
            self._schedule(t, "arrival", job=Job(f"JOB-{idx:05d}", t, due, priority))

    def run(self) -> dict[str, Any]:
        self._generate_demand_events()
        horizon = self.config.duration_hours * 60.0
        while self.events:
            event = heapq.heappop(self.events)
            if event.at > horizon:
                break
            self.now = event.at
            if event.kind in {"arrival", "arrival_retry"}:
                self._handle_arrival(event)
            elif event.kind == "machine_done":
                self._handle_machine_done(event)
            elif event.kind == "quality_done":
                self._handle_quality_done(event)
            elif event.kind == "rework_done":
                self._handle_rework_done(event)
            elif event.kind == "reinspect_done":
                self._transfer_or_block("Q", event.server_idx, event.job)  # type: ignore[arg-type]
                self._retry_blocked("C")
            elif event.kind == "repair_done":
                server = self.servers[event.stage][event.server_idx]
                server.wear = max(0.12, server.wear * 0.72)
                server.condition_history.clear()
                self._start_machine_operation(event.stage, event.server_idx, event.job)  # type: ignore[arg-type]
            elif event.kind == "maintenance_done":
                server = self.servers[event.stage][event.server_idx]
                server.wear = max(0.08, server.wear * 0.30)
                server.condition_history.clear()
                self._start_machine_operation(event.stage, event.server_idx, event.job)  # type: ignore[arg-type]
            elif event.kind == "planned_maintenance_start":
                self._begin_planned_maintenance(event.stage, event.server_idx)
            elif event.kind == "scheduled_maintenance_done":
                server = self.servers[event.stage][event.server_idx]
                server.wear = max(0.08, server.wear * 0.30)
                server.condition_history.clear()
                server.state = MachineState.IDLE
                self._try_start(event.stage)
        self.now = horizon
        return self.metrics()

    def _average_queue_lengths(self) -> dict[str, float]:
        horizon = self.config.duration_hours * 60.0
        history = self.queue_history + [(horizon, self.queue_history[-1][1])]
        area = {s: 0.0 for s in self.stages}
        for (t0, values), (t1, _) in zip(history, history[1:], strict=False):
            dt = max(0.0, min(t1, horizon) - min(t0, horizon))
            for s in self.stages:
                area[s] += values[s] * dt
        return {s: round(area[s] / max(horizon, 1e-9), 3) for s in self.stages}

    def metrics(self) -> dict[str, Any]:
        horizon = self.config.duration_hours * 60.0
        machine_metrics: dict[str, Any] = {}
        total_planned = 0.0
        total_unplanned = 0.0
        total_busy = 0.0
        total_ideal = 0.0
        total_energy = 0.0
        for stage in self.machine_stages:
            cfg = self.config.machines[stage]
            st = self.stats[stage]
            capacity_min = horizon * cfg.capacity
            availability = max(0.0, 1.0 - (st.planned_downtime_min + st.unplanned_downtime_min) / max(capacity_min, 1.0))
            performance = min(1.0, (st.cycles * cfg.cycle_time_min) / max(st.busy_min, 1e-9))
            utilization = min(1.0, st.busy_min / max(capacity_min, 1e-9))
            machine_metrics[cfg.machine_id] = {
                "stage": stage,
                "process": cfg.process,
                "cycles": st.cycles,
                "utilization": round(utilization, 4),
                "availability": round(availability, 4),
                "performance": round(performance, 4),
                "planned_downtime_min": round(st.planned_downtime_min, 3),
                "unplanned_downtime_min": round(st.unplanned_downtime_min, 3),
                "blocked_min": round(st.blocked_min, 3),
                "failures": st.failures,
                "maintenance_events": st.maintenance_events,
                "energy_kwh": round(st.energy_kwh, 3),
            }
            total_planned += st.planned_downtime_min
            total_unplanned += st.unplanned_downtime_min
            total_busy += st.busy_min
            total_ideal += st.cycles * cfg.cycle_time_min
            total_energy += st.energy_kwh
        capacity_total = horizon * sum(self.config.machines[s].capacity for s in self.machine_stages)
        availability = max(0.0, 1.0 - (total_planned + total_unplanned) / max(capacity_total, 1.0))
        performance = min(1.0, total_ideal / max(total_busy, 1e-9))
        good_units = max(0, self.finished - self.defects_missed)
        quality = good_units / max(self.finished + self.scrap, 1)
        oee = availability * performance * quality
        queues = self._average_queue_lengths()
        wip = max(0, self.created - self.finished - self.scrap)
        return {
            "run_id": self.run_id,
            "duration_hours": self.config.duration_hours,
            "demand_created": self.created,
            "throughput_units": self.finished,
            "throughput_per_hour": round(self.finished / max(self.config.duration_hours, 1e-9), 3),
            "wip_end": wip,
            "average_queue_lengths": queues,
            "lead_time_mean_min": round(statistics.fmean(self.lead_times), 3) if self.lead_times else None,
            "lead_time_median_min": round(statistics.median(self.lead_times), 3) if self.lead_times else None,
            "planned_downtime_min": round(total_planned, 3),
            "unplanned_downtime_min": round(total_unplanned, 3),
            "scrap_units": self.scrap,
            "scrap_rate": round(self.scrap / max(self.created, 1), 4),
            "defect_rate": round(self.defects_generated / max(self.created, 1), 4),
            "rework_units": self.rework,
            "false_positive_inspections": self.false_positive_inspections,
            "late_orders": self.late_orders,
            "energy_kwh": round(total_energy, 3),
            "energy_per_finished_unit_kwh": round(total_energy / max(self.finished, 1), 4),
            "overflow_events": self.overflow_events,
            "oee": {
                "availability": round(availability, 4),
                "performance": round(performance, 4),
                "quality": round(quality, 4),
                "oee": round(oee, 4),
            },
            "machines": machine_metrics,
            "assumptions": {
                "synthetic_data": True,
                "simulation_type": "student-scale event-calendar operational twin",
                "guaranteed_real_world_impact": False,
                "demand_periods": [
                    {
                        "start_min": period.start_min,
                        "end_min": period.end_min,
                        "multiplier": period.multiplier,
                        "label": period.label,
                    }
                    for period in self.config.demand_periods
                ],
            },
        }


def run_baseline(duration_hours: float = 8.0, seed: int = 7) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sim = FactorySimulator(baseline_config(duration_hours), seed=seed)
    metrics = sim.run()
    return metrics, sim.telemetry
