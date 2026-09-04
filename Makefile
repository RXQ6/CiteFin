UV_CACHE_DIR ?= $(CURDIR)/.uv-cache
UV_PYTHON_INSTALL_DIR ?= $(CURDIR)/.uv-python

export UV_CACHE_DIR
export UV_PYTHON_INSTALL_DIR

.PHONY: setup test lint format typecheck check run golden migrate verify-feature

setup:
	uv sync --frozen

test:
	uv run pytest

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

format:
	uv run ruff check --fix src tests
	uv run ruff format src tests

typecheck:
	uv run mypy

golden:
	uv run python tests/golden/validate.py

check: lint typecheck golden test

verify-feature:
	@if [ "$(FEATURE)" = "INFRA-001" ] || [ "$(FEATURE)" = "F001" ]; then \
		$(MAKE) check; \
	else \
		echo "No executable verifier is registered for $(FEATURE)"; \
		exit 2; \
	fi

run:
	uv run uvicorn citefin.main:app --reload --host 127.0.0.1 --port 8000

migrate:
	uv run alembic upgrade head
