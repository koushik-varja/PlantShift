PYTHON ?= python
.PHONY: test lint typecheck train benchmark benchmark-e2e api docker-up docker-down frontend-build

test:
	$(PYTHON) -m pytest
lint:
	$(PYTHON) -m ruff check .
typecheck:
	$(PYTHON) -m mypy factory_simulator telemetry digital_twin analytics scenario_engine optimizer backend/app ml
train:
	$(PYTHON) -m scripts.train_ml
benchmark:
	$(PYTHON) -m benchmarks.run_benchmarks
benchmark-e2e:
	$(PYTHON) -m benchmarks.run_e2e_ingestion --admin-token "$$ADMIN_TOKEN"
api:
	uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
frontend-build:
	cd frontend && npm run build
docker-up:
	docker compose up --build
docker-down:
	docker compose down
