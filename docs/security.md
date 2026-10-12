# Security review

Implemented controls:

- strict Pydantic telemetry and scenario parameter validation;
- administrative scenario/optimizer/benchmark controls require `X-Admin-Token` from environment configuration;
- no production credentials are hardcoded;
- CORS is restricted to configured origins;
- the low control-plane per-IP rate limiter remains enabled for ordinary API routes; `/api/telemetry` and `/api/telemetry/batch` are exempt from that UI/control bucket so the internal MQTT bridge is not throttled at 120 requests/minute;
- SQLAlchemy parameterization is used instead of string-built SQL;
- MQTT payload size and broker queue depth are bounded;
- bridge input queue, batch size, flush window and HTTP retry count are bounded, with exponential backoff/jitter and a DLQ after retry exhaustion;
- frontend does not bundle the administrative token; the user supplies it at runtime;
- no shell-execution or arbitrary command endpoint exists.

Known demo limitation: Mosquitto allows anonymous access inside the Compose network. The broker is intended for local demonstration; production deployment would require TLS, authenticated clients, ACLs, secret management and operational monitoring. PlantShift does not claim those controls are implemented.


## Docker build context safety

The repository root `.dockerignore` excludes `.env`, VCS metadata, virtual environments, Python caches/databases, frontend install/build artifacts and generated Joblib model files from the backend build context. The frontend has its own `.dockerignore` because Compose builds it from `./frontend`. Runtime secrets such as `POSTGRES_PASSWORD` and `ADMIN_TOKEN` enter containers only through Compose environment configuration; they are not intentionally copied into image layers. `.env.example`, source, tests, Alembic files, package manifests and `ml/artifacts/evaluation.json` remain available to the build.
