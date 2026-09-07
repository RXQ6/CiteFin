UV_CACHE_DIR ?= $(CURDIR)/.uv-cache
UV_PYTHON_INSTALL_DIR ?= $(CURDIR)/.uv-python

export UV_CACHE_DIR
export UV_PYTHON_INSTALL_DIR

.PHONY: setup test lint format typecheck check run golden migrate prepare-f004-review verify-feature

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
	@if [ "$(FEATURE)" = "F001" ] || [ "$(FEATURE)" = "F002" ] || [ "$(FEATURE)" = "F003" ]; then \
		$(MAKE) check; \
	elif [ "$(FEATURE)" = "F005" ]; then \
		$(MAKE) check && uv run python scripts/verify_f005.py; \
	elif [ "$(FEATURE)" = "F006" ]; then \
		$(MAKE) check && uv run python scripts/verify_f006.py; \
	elif [ "$(FEATURE)" = "F007" ]; then \
		$(MAKE) check && uv run python scripts/verify_f007.py; \
	elif [ "$(FEATURE)" = "F008" ]; then \
		$(MAKE) check && uv run python scripts/verify_f008.py; \
	elif [ "$(FEATURE)" = "F009" ]; then \
		$(MAKE) check && uv run python scripts/verify_f009.py; \
	elif [ "$(FEATURE)" = "F010" ]; then \
		$(MAKE) check && uv run python scripts/verify_f010.py; \
	elif [ "$(FEATURE)" = "F011" ]; then \
		$(MAKE) check && uv run python scripts/verify_f011.py; \
	elif [ "$(FEATURE)" = "F012" ]; then \
		$(MAKE) check && uv run python scripts/verify_f012.py; \
	elif [ "$(FEATURE)" = "F013" ]; then \
		$(MAKE) check && uv run python scripts/verify_f013.py; \
	elif [ "$(FEATURE)" = "F014" ]; then \
		$(MAKE) check && uv run python scripts/verify_f014.py; \
	elif [ "$(FEATURE)" = "F015" ]; then \
		$(MAKE) check && uv run python scripts/verify_f015.py; \
	elif [ "$(FEATURE)" = "F016" ]; then \
		$(MAKE) check && uv run python scripts/verify_f016.py; \
	elif [ "$(FEATURE)" = "F017" ]; then \
		$(MAKE) check && uv run python scripts/verify_f017.py; \
	elif [ "$(FEATURE)" = "F018" ]; then \
		$(MAKE) check && uv run python scripts/verify_f018.py; \
	else \
		echo "No executable verifier is registered for $(FEATURE)"; \
		exit 2; \
	fi

run:
	uv run uvicorn citefin.main:app --reload --host 127.0.0.1 --port 8000

migrate:
	uv run alembic upgrade head

prepare-f004-review:
	uv run python scripts/prepare_f004_review.py
