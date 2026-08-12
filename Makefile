# Makefile for tool-swap — behaviour 10 wiring
# Wraps ruff (check + format), mypy (strict), and pytest.

.PHONY: help lint format typecheck test test-docker

# Use the venv interpreter so tools are found even when .venv/bin is not on PATH.
# Overridable from the environment (e.g. CI can pass PY=/usr/bin/python3).
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

help: ## Show this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*##"}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

lint: ## Run ruff (check + format check) and mypy strict over src/
	$(PY) -m ruff check src/
	$(PY) -m ruff format --check src/
	$(PY) -m mypy src/

format: ## Run ruff formatter over src/
	$(PY) -m ruff format src/

typecheck: ## Run mypy strict type-checking over src/
	$(PY) -m mypy src/

# Sentinel guard: when TSWAP_IN_MAKE_TEST is set, skip recursive make test.
# Prevents infinite recursion when test_makefile.py's meta-test shells out
# to `make test` from within a `make test` invocation.
test: ## Run pytest (excludes docker/gpu/slow markers by default)
ifdef TSWAP_IN_MAKE_TEST
	@echo "SKIP: already inside make test (TSWAP_IN_MAKE_TEST set)"
	@exit 0
endif
	TSWAP_IN_MAKE_TEST=1 $(PY) -m pytest

test-docker: ## Run pytest including docker-marked tests
	$(PY) -m pytest -m 'docker'
