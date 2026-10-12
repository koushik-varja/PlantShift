from __future__ import annotations

import asyncio
import json
import os
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.exc import IntegrityError

from analytics import diagnose
from digital_twin import TwinStore
from ml import FailureRiskService
from optimizer import (
    BusinessAssumptions,
    PortfolioConstraints,
    build_roadmap,
    business_value,
    optimize_portfolio,
    sensitivity_stability,
)
from scenario_engine import CATALOG, Scenario, monte_carlo, run_scenario
from telemetry import TelemetryIngestor
from telemetry.schemas import TelemetryEvent

from .db import ProcessedEvent, ScenarioRecord, SessionLocal, TelemetryRecord, init_db
from .schemas import (
    BusinessValueRequest,
    MaintenanceWindowRequest,
    MonteCarloRequest,
    PortfolioRequest,
    RoadmapRequest,
    ScenarioRequest,
    SensitivityRequest,
)
from .services import execute_scenario, maintenance_window_comparison

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if origin.strip()]
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
TELEMETRY_INGEST_PATHS = {"/api/telemetry", "/api/telemetry/batch"}

requests_by_ip: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=RATE_LIMIT_PER_MINUTE + 10))
twins = TwinStore()
risk_service: FailureRiskService | None = None
ingestor = TelemetryIngestor(twins)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global ingestor, risk_service

    init_db()
    model_path = Path(os.getenv("ML_MODEL_PATH", "ml/artifacts/failure_risk.joblib"))
    if model_path.exists():
        try:
            risk_service = FailureRiskService(model_path)
            ingestor = TelemetryIngestor(twins, predictor=risk_service.predict)
        except Exception:
            risk_service = None
            ingestor = TelemetryIngestor(twins)
    yield


app = FastAPI(title="PlantShift API", version="1.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Admin-Token"],
)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path == "/health" or request.url.path in TELEMETRY_INGEST_PATHS:
        return await call_next(request)

    ip = request.client.host if request.client else "unknown"
    now = monotonic()
    bucket = requests_by_ip[ip]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_PER_MINUTE:
        return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
    bucket.append(now)
    return await call_next(request)


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="administrative controls disabled until ADMIN_TOKEN is configured",
        )
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid admin token",
        )


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "plantshift",
        "runtime_ml": risk_service is not None,
    }


@app.get("/api/catalog")
def catalog() -> list[dict[str, Any]]:
    return [CATALOG[key].to_dict() for key in CATALOG]


@app.get("/api/baseline")
def baseline(duration_hours: float = 8, seed: int = 7) -> dict[str, Any]:
    if not 0 < duration_hours <= 72:
        raise HTTPException(status_code=422, detail="duration_hours must be in (0, 72]")
    result = run_scenario(
        Scenario("baseline", []),
        duration_hours=duration_hours,
        seed=seed,
    )
    result["diagnosis"] = diagnose(result)
    return result


@app.post("/api/scenarios/run")
def scenario_run(
    payload: ScenarioRequest,
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return execute_scenario(
            payload.name,
            payload.interventions,
            payload.duration_hours,
            payload.seed,
            payload.parameters.model_dump(exclude_none=True),
            payload.cost_overrides,
            payload.effort_overrides,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/scenarios/monte-carlo")
def scenario_monte_carlo(
    payload: MonteCarloRequest,
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return monte_carlo(
            Scenario(
                payload.name,
                payload.interventions,
                costs=payload.cost_overrides,
                efforts=payload.effort_overrides,
                parameters=payload.parameters.model_dump(exclude_none=True),
            ),
            runs=payload.runs,
            duration_hours=payload.duration_hours,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/scenarios/history")
def scenario_history(limit: int = 20) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.query(ScenarioRecord).order_by(ScenarioRecord.created_at.desc()).limit(min(max(limit, 1), 100)).all()
        return [
            {
                "id": row.id,
                "name": row.name,
                "created_at": row.created_at.isoformat(),
                "interventions": row.interventions,
                "duration_ms": row.duration_ms,
            }
            for row in rows
        ]


def _persist_batch(events: list[TelemetryEvent]) -> dict[str, Any]:
    # Preserve event-instance identity: for a repeated event_id, the first event that
    # is successfully persisted wins. Later same-batch payloads never replace it.
    accepted_events: list[TelemetryEvent] = []
    duplicate_ids: list[str] = []
    with SessionLocal() as db:
        ids = list(dict.fromkeys(event.event_id for event in events))
        existing = {row[0] for row in db.query(ProcessedEvent.event_id).filter(ProcessedEvent.event_id.in_(ids)).all()} if ids else set()
        accepted_in_batch: set[str] = set()
        now = datetime.now(UTC)
        for event in events:
            if event.event_id in existing or event.event_id in accepted_in_batch:
                duplicate_ids.append(event.event_id)
                continue
            body = event.model_dump(mode="json")
            db.add(ProcessedEvent(event_id=event.event_id, first_seen_at=now))
            db.add(
                TelemetryRecord(
                    event_id=event.event_id,
                    machine_id=event.machine_id,
                    timestamp=event.timestamp,
                    ingest_timestamp=now,
                    payload=body,
                )
            )
            accepted_events.append(event)
            accepted_in_batch.add(event.event_id)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # Rare concurrent-race fallback. Reprocess in original order and mark an
            # event_id handled after its first attempt, so a later same-batch payload
            # can never become the winner if the first one raced or already existed.
            accepted_events = []
            duplicate_ids = []
            handled_ids: set[str] = set()
            for event in events:
                if event.event_id in handled_ids:
                    duplicate_ids.append(event.event_id)
                    continue
                handled_ids.add(event.event_id)
                with SessionLocal() as one:
                    if one.get(ProcessedEvent, event.event_id) is not None:
                        duplicate_ids.append(event.event_id)
                        continue
                    now_one = datetime.now(UTC)
                    body = event.model_dump(mode="json")
                    try:
                        one.add(
                            ProcessedEvent(
                                event_id=event.event_id,
                                first_seen_at=now_one,
                            )
                        )
                        one.add(
                            TelemetryRecord(
                                event_id=event.event_id,
                                machine_id=event.machine_id,
                                timestamp=event.timestamp,
                                ingest_timestamp=now_one,
                                payload=body,
                            )
                        )
                        one.commit()
                        accepted_events.append(event)
                    except IntegrityError:
                        one.rollback()
                        duplicate_ids.append(event.event_id)

    late = 0
    for event in accepted_events:
        result = ingestor.ingest(
            event.model_dump(mode="json"),
            skip_memory_dedupe=True,
        )
        late += int(result.late)
    accepted_ids = [event.event_id for event in accepted_events]
    return {
        "accepted": len(accepted_events),
        "duplicates": len(duplicate_ids),
        "late": late,
        "accepted_event_ids": accepted_ids,
    }


@app.post("/api/telemetry")
def ingest_telemetry(payload: TelemetryEvent) -> dict[str, Any]:
    result = _persist_batch([payload])
    return {
        "accepted": result["accepted"] == 1,
        "duplicate": result["accepted"] == 0,
        "late": bool(result["late"]),
        "error": None,
    }


@app.post("/api/telemetry/batch")
def ingest_telemetry_batch(payload: list[TelemetryEvent]) -> dict[str, Any]:
    if not payload or len(payload) > 200:
        raise HTTPException(status_code=422, detail="batch size must be 1..200")
    return _persist_batch(payload)


@app.get("/api/telemetry/stats")
def telemetry_stats() -> dict[str, int]:
    return ingestor.stats()


@app.get("/api/benchmarks/ingestion")
def ingestion_benchmark_stats(
    prefix: str,
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    if not prefix or len(prefix) > 80:
        raise HTTPException(status_code=422, detail="prefix must be 1..80 characters")
    with SessionLocal() as db:
        rows = db.query(TelemetryRecord).filter(TelemetryRecord.event_id.like(f"{prefix}%")).all()

    latencies = []
    for row in rows:
        event_ts = row.timestamp
        ingest_ts = row.ingest_timestamp
        if event_ts.tzinfo is None:
            event_ts = event_ts.replace(tzinfo=UTC)
        if ingest_ts.tzinfo is None:
            ingest_ts = ingest_ts.replace(tzinfo=UTC)
        latencies.append(max(0.0, (ingest_ts - event_ts).total_seconds() * 1000.0))
    latencies.sort()

    def percentile(value: float) -> float | None:
        if not latencies:
            return None
        index = min(len(latencies) - 1, round((len(latencies) - 1) * value))
        return round(latencies[index], 3)

    return {
        "count": len(rows),
        "latency_ms": {
            "p50": percentile(0.5),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
        },
        "label": "MEASURED from persisted event and ingest timestamps",
    }


@app.get("/api/twins")
def all_twins() -> list[dict[str, Any]]:
    return twins.all()


@app.get("/api/twins/{machine_id}")
def get_twin(machine_id: str) -> dict[str, Any]:
    twin = twins.get(machine_id)
    if not twin:
        raise HTTPException(status_code=404, detail="machine twin not found")
    return twin


@app.get("/api/machines/{machine_id}/health")
def machine_health(machine_id: str) -> dict[str, Any]:
    twin = twins.get(machine_id)
    if not twin:
        raise HTTPException(status_code=404, detail="machine twin not found")
    return {
        key: twin.get(key)
        for key in (
            "machine_id",
            "health_state",
            "failure_probability",
            "model_version",
            "feature_timestamp",
            "health_features",
            "warning_reason",
            "updated_at",
        )
    }


@app.get("/api/twins/stream/live")
async def twin_stream() -> StreamingResponse:
    async def generate():
        last = ""
        while True:
            items = []
            for twin in twins.all():
                twin.pop("recent_telemetry", None)
                twin.pop("health_features", None)
                items.append(twin)
            payload = json.dumps(items, default=str, separators=(",", ":"))
            if payload != last:
                yield f"event: twins\ndata: {payload}\n\n"
                last = payload
            await asyncio.sleep(1.0)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/optimizer/portfolio")
def portfolio(
    payload: PortfolioRequest,
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    assumptions = BusinessAssumptions(**payload.business_assumptions.model_dump())
    constraints = PortfolioConstraints(
        budget=payload.budget,
        implementation_capacity=payload.implementation_capacity,
        maximum_risk=payload.maximum_risk,
        objective=payload.objective,
        weights=payload.weights,
        evaluation_runs=payload.evaluation_runs,
        cost_overrides=payload.cost_overrides,
        effort_overrides=payload.effort_overrides,
        business_assumptions=assumptions,
        scenario_parameters=payload.scenario_parameters.model_dump(exclude_none=True),
    )
    try:
        return optimize_portfolio(constraints, duration_hours=payload.duration_hours)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/roadmap")
def roadmap(payload: RoadmapRequest) -> list[dict[str, Any]]:
    try:
        return build_roadmap(
            payload.interventions,
            max_effort_per_phase=payload.max_effort_per_phase,
            max_cost_per_phase=payload.max_cost_per_phase,
            cost_overrides=payload.cost_overrides,
            effort_overrides=payload.effort_overrides,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/maintenance/windows")
def maintenance_windows(
    payload: MaintenanceWindowRequest,
    _: None = Depends(require_admin),
) -> list[dict[str, Any]]:
    try:
        return maintenance_window_comparison(
            payload.stage,
            payload.duration_hours,
            payload.seed,
            payload.planned_duration_min,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/business-value")
def value_model(
    payload: BusinessValueRequest,
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    try:
        scenario = payload.scenario
        base = run_scenario(
            Scenario("baseline", []),
            duration_hours=scenario.duration_hours,
            seed=scenario.seed,
        )
        future = run_scenario(
            Scenario(
                scenario.name,
                scenario.interventions,
                costs=scenario.cost_overrides,
                efforts=scenario.effort_overrides,
                parameters=scenario.parameters.model_dump(exclude_none=True),
            ),
            duration_hours=scenario.duration_hours,
            seed=scenario.seed,
        )
        assumptions = BusinessAssumptions(
            payload.value_per_finished_unit,
            payload.downtime_cost_per_hour,
            payload.scrap_cost_per_unit,
            payload.rework_cost_per_unit,
            payload.energy_cost_per_kwh,
            payload.planned_maintenance_cost,
            payload.unplanned_maintenance_cost,
        )
        return business_value(base, future, assumptions)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/sensitivity")
def sensitivity(
    payload: SensitivityRequest,
    _: None = Depends(require_admin),
) -> dict[str, Any]:
    try:
        first = payload.scenarios[0]
        mismatched_seed = [scenario.name for scenario in payload.scenarios[1:] if scenario.seed != first.seed]
        mismatched_horizon = [scenario.name for scenario in payload.scenarios[1:] if scenario.duration_hours != first.duration_hours]
        if mismatched_seed:
            raise ValueError(
                "Sensitivity scenarios must use the same seed for a comparable common baseline; "
                f"expected seed={first.seed}, mismatched scenarios={mismatched_seed}."
            )
        if mismatched_horizon:
            raise ValueError(
                "Sensitivity scenarios must use the same duration_hours for a comparable common baseline; "
                f"expected duration_hours={first.duration_hours}, mismatched scenarios={mismatched_horizon}."
            )

        base = run_scenario(
            Scenario("baseline", []),
            duration_hours=first.duration_hours,
            seed=first.seed,
        )
        candidates = []
        for scenario in payload.scenarios:
            result = run_scenario(
                Scenario(
                    scenario.name,
                    scenario.interventions,
                    costs=scenario.cost_overrides,
                    efforts=scenario.effort_overrides,
                    parameters=scenario.parameters.model_dump(exclude_none=True),
                ),
                duration_hours=first.duration_hours,
                seed=first.seed,
            )
            candidates.append(
                {
                    "name": scenario.name,
                    "cost": result["transformation_cost"],
                    "metrics": result,
                }
            )

        assumptions = BusinessAssumptions(
            payload.value_per_finished_unit,
            payload.downtime_cost_per_hour,
            payload.scrap_cost_per_unit,
            payload.rework_cost_per_unit,
            payload.energy_cost_per_kwh,
            payload.planned_maintenance_cost,
            payload.unplanned_maintenance_cost,
        )
        return sensitivity_stability(base, candidates, assumptions)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/ml/evaluation")
def ml_evaluation() -> dict[str, Any]:
    path = Path(os.getenv("ML_EVAL_PATH", "ml/artifacts/evaluation.json"))
    if path.exists():
        return json.loads(path.read_text())
    return {
        "status": "not_trained",
        "message": "Run python scripts/train_ml.py",
    }
