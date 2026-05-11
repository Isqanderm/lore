.PHONY: dev test test-unit test-integration test-e2e lint format type-check migrate migration

dev:
	docker compose up -d postgres redis
	uv run uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000

test:
	uv run pytest tests/ -v

test-unit:
	uv run pytest tests/unit/ -v -m unit

test-integration:
	uv run pytest tests/integration/ -v -m integration

test-e2e:
	uv run pytest tests/e2e/ -v -m e2e

lint:
	uv run ruff check .

format:
	uv run ruff format .

type-check:
	uv run mypy lore/ apps/

migrate:
	uv run alembic upgrade head

migration:
	uv run alembic revision --autogenerate -m "$(name)"
