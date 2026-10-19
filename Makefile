.PHONY: help install dev docker-up docker-down docker-logs migrate migration worker test lint clean

help:
	@echo "LeadFlow Platform - Developer CLI Commands"
	@echo "----------------------------------------------------"
	@echo "  make install        Install backend and frontend dependencies"
	@echo "  make dev            Run all dev services (Docker DB+Redis + local apps)"
	@echo "  make docker-up      Start all containers (Postgres, Redis, API, Worker, Web)"
	@echo "  make docker-down    Stop all containers"
	@echo "  make docker-logs    Tail container logs"
	@echo "  make migrate        Apply Alembic database migrations"
	@echo "  make migration      Generate a new Alembic migration revision"
	@echo "  make worker         Run ARQ background worker locally"
	@echo "  make test           Run backend test suite"
	@echo "  make lint           Run code formatting and linters"
	@echo "  make clean          Clean temporary files and caches"

install:
	@echo "Installing backend dependencies..."
	cd apps/api && pip install -e .
	@echo "Installing frontend dependencies..."
	cd apps/web && npm install

docker-up:
	docker compose -f infra/docker/docker-compose.yml up -d

docker-down:
	docker compose -f infra/docker/docker-compose.yml down

docker-logs:
	docker compose -f infra/docker/docker-compose.yml logs -f

migrate:
	cd apps/api && alembic upgrade head

migration:
	@read -p "Enter migration message: " msg; \
	cd apps/api && alembic revision --autogenerate -m "$$msg"

worker:
	cd apps/api && python -m arq app.jobs.worker.WorkerSettings

dev-api:
	cd apps/api && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-web:
	cd apps/web && npm run dev

test:
	cd apps/api && pytest -v tests/

lint:
	cd apps/api && ruff check .
	cd apps/web && npm run lint

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".next" -exec rm -rf {} +
