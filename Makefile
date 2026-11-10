# Development environments, caches, and test artifacts belong in this sandbox.
# Override SANDBOX_DIR, VENV_DIR, or PYTHON explicitly when needed.
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

SANDBOX_DIR ?= $(HOME)/sandbox/enterprise-api-testing-framework
VENV_DIR ?= $(SANDBOX_DIR)/venv
PYTHON ?= $(VENV_DIR)/bin/python
BOOTSTRAP_PYTHON ?= python3
PYTEST_ARGS ?=
WORKERS ?= auto
INPUTS ?=
LOG_FILE ?=
REPORT ?=
DOCKER ?= docker
COMPOSE ?= docker compose
BASE_IMAGE ?= python:3.11-slim
OPEN ?= $(if $(filter Darwin,$(shell uname -s)),open,xdg-open)

export PYTHONDONTWRITEBYTECODE := 1
export PIP_CACHE_DIR := $(SANDBOX_DIR)/pip-cache
export XDG_CACHE_HOME := $(SANDBOX_DIR)/cache

.PHONY: help install require-env check-api check-redis test test-full test-crud \
        test-contract test-parallel test-offline contracts mutations evaluation \
        history logs report docker-build docker-ready docker-run docker-run-parallel \
        docker-clean pin-base-image audit lint clean console build-console mcp-setup publication export-source

help: ## Show available commands; no installation or test execution
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-25s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Create the sandbox venv if missing and install requirements-dev.txt
	@mkdir -p "$(SANDBOX_DIR)" "$(PIP_CACHE_DIR)" "$(SANDBOX_DIR)/install-tmp"; \
	if [ ! -d "$(VENV_DIR)" ]; then "$(BOOTSTRAP_PYTHON)" -m venv "$(VENV_DIR)"; fi; \
	test -x "$(PYTHON)" || { echo 'No usable venv Python; check VENV_DIR/PYTHON.' >&2; exit 1; }; \
	"$(PYTHON)" -c 'import sys; sys.exit("Refusing to install into global Python") if sys.prefix == sys.base_prefix else None'; \
	TMPDIR="$(SANDBOX_DIR)/install-tmp" "$(PYTHON)" -m pip install -r requirements-dev.txt

require-env:
	@test -x "$(PYTHON)" || { echo 'Run make install or select an existing sandbox venv with PYTHON.' >&2; exit 1; }
	@"$(PYTHON)" -c 'import sys; sys.exit("Select a virtual environment with PYTHON; global Python is not used") if sys.prefix == sys.base_prefix else None'

# Live commands validate the explicit environment/.env through the normal
# settings model, including HTTPS outside loopback. No synthetic fallback.
check-api: require-env
	@FRAMEWORK_OFFLINE=0 "$(PYTHON)" -c 'from config.settings import settings; assert settings.api_base_url and settings.api_username and settings.api_password, "Configure API_BASE_URL, API_USERNAME, and API_PASSWORD"'

check-redis: check-api
	@FRAMEWORK_OFFLINE=0 "$(PYTHON)" -c 'import sys; from config.settings import settings; sys.exit("Parallel live tests require REDIS_URL") if not settings.redis_url else None'

# Each live pytest invocation keeps the 80% coverage gate. A narrow marker
# selection can fail that gate; the output must not be mistaken for a full run.
define run_pytest
	@mkdir -p "$(SANDBOX_DIR)/runs"; \
	output=$$(mktemp -d "$(SANDBOX_DIR)/runs/$(1)-$$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX"); \
	mkdir "$$output/tmp"; \
	printf 'Artifacts: %s\nCoverage gate: 80%% with branch measurement enabled.\n' "$$output"; \
	export FRAMEWORK_OFFLINE=0 FRAMEWORK_RESULTS_DIR="$$output" LOG_FILE="$$output/http.jsonl"; \
	export TMPDIR="$$output/tmp" COVERAGE_FILE="$$output/.coverage"; \
	export FRAMEWORK_RUN_ID="$$(basename "$$output")"; \
	export FRAMEWORK_ENVIRONMENT="$${FRAMEWORK_ENVIRONMENT:-configured-integration}"; \
	export FRAMEWORK_RUN_STARTED_UTC=$$("$(PYTHON)" -c 'from datetime import UTC, datetime; print(datetime.now(UTC).isoformat())'); \
	"$(PYTHON)" -m pytest -o addopts='' --verbose --tb=short --strict-markers \
	  --timeout=60 -p no:cacheprovider --basetemp="$$output/pytest-tmp" \
	  --junitxml="$$output/junit.xml" --html="$$output/report.html" --self-contained-html \
	  --cov=src --cov=config --cov-branch --cov-fail-under=80 \
	  --cov-report=term-missing --cov-report="xml:$$output/coverage.xml" \
	  --cov-report="html:$$output/htmlcov" $(2) $(PYTEST_ARGS) 2>&1 | tee "$$output/pytest.log"
endef

test: test-full ## Run the full configured suite with sandbox artifacts

test-full: check-api ## Run the full configured suite and retain its 80% coverage gate
	$(call run_pytest,full,)

test-crud: check-api ## Select CRUD checks; retain the coverage gate and report its result
	$(call run_pytest,crud,-m crud)

test-contract: check-api ## Select contract checks; retain the coverage gate and report its result
	$(call run_pytest,contract,-m contract)

test-parallel: check-redis ## Run configured tests with Redis and WORKERS=auto by default
	$(call run_pytest,parallel,-n $(WORKERS))

# These scripts require a new leaf directory. Keep their unique parent as
# retained evidence; never reuse a previous run or remove it automatically.
define run_script
	@mkdir -p "$(SANDBOX_DIR)/$(1)"; \
	output=$$(mktemp -d "$(SANDBOX_DIR)/$(1)/run-$$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX"); \
	mkdir "$$output/tmp"; \
	printf 'Artifacts: %s/evidence\n' "$$output"; \
	TMPDIR="$$output/tmp" "$(PYTHON)" $(2) --output "$$output/evidence" $(3)
endef

test-offline: require-env ## Run the offline acceptance path without external credentials
	$(call run_script,runs,scripts/run_offline.py,-- $(PYTEST_ARGS))

contracts: require-env ## Check versioned model schema snapshots without updating them
	"$(PYTHON)" scripts/check_contracts.py

mutations: require-env ## Test seeded client defects in isolated source copies
	$(call run_script,mutations,scripts/mutation_check.py,)

evaluation: require-env ## Evaluate the supplied synthetic response sample
	$(call run_script,evaluations,scripts/evaluate_responses.py,--config fixtures/evaluation/config.json --input fixtures/evaluation/synthetic_responses.jsonl)

history: require-env ## Build a history report; provide INPUTS='run1.jsonl run2.jsonl'
	@test -n "$(INPUTS)" || { echo 'Provide phase evidence with INPUTS; no report was created.' >&2; exit 2; }
	$(call run_script,history,scripts/build_history_report.py,$(INPUTS))

console: require-env ## Build/reuse the React console and serve a private loopback session
	"$(PYTHON)" scripts/console.py --sandbox "$(SANDBOX_DIR)"

build-console: require-env ## Build locked frontend assets entirely in sandbox
	"$(PYTHON)" scripts/build_console.py --sandbox "$(SANDBOX_DIR)"

mcp-setup: require-env ## Prepare the isolated optional SDK and print local client configuration
	"$(PYTHON)" scripts/setup_mcp.py --sandbox "$(SANDBOX_DIR)/mcp" --data-dir "$(SANDBOX_DIR)/control"

publication: require-env ## Scan tracked and new files for secrets without printing values
	"$(PYTHON)" scripts/check_publication.py

export-source: require-env ## Create a new source archive without Git metadata or ignored files
	$(call run_script,exports,scripts/export_source.py,)

logs: ## Tail an explicit retained log: make logs LOG_FILE=/path/to/http.jsonl
	@test -n "$(LOG_FILE)" && test -f "$(LOG_FILE)" || { echo 'Provide an existing LOG_FILE.' >&2; exit 2; }
	tail -f "$(LOG_FILE)"

report: ## Open an explicit retained report: make report REPORT=/path/to/report.html
	@test -n "$(REPORT)" && test -f "$(REPORT)" || { echo 'Provide an existing REPORT.' >&2; exit 2; }
	$(OPEN) "$(REPORT)"

docker-build: ## Build the existing runtime Docker image
	$(DOCKER) build --target runtime -t api-testing-framework:local .

# Running requires an already prepared local environment. This preflight only
# inspects images; it neither builds nor downloads them. Use docker-build as an
# explicit separate action when preparing the runtime image.
docker-ready:
	@test -f .env || { echo 'Configure .env before running the Compose-backed suite.' >&2; exit 2; }
	@$(COMPOSE) -f docker-compose.yml config --images | sort -u | while IFS= read -r image; do \
	  $(DOCKER) image inspect "$$image" > /dev/null || { echo 'A required local image is missing; prepare the Docker environment first.' >&2; exit 2; }; \
	done

# Compose uses a unique project and Redis name, avoiding other sessions.
# Bind mounts override the repository-local defaults. Matching the host UID/GID
# lets the non-root test process write only its task-owned artifact directories.
# The exit trap stops only this unique project's services; no volumes or orphan
# containers are removed, and no image deletion is performed.
define run_docker
	@mkdir -p "$(SANDBOX_DIR)/docker-runs"; \
	output=$$(mktemp -d "$(SANDBOX_DIR)/docker-runs/run-$$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX"); \
	mkdir "$$output/logs" "$$output/reports" "$$output/tmp"; \
	project="api-fw-$$(basename "$$output" | tr '[:upper:]' '[:lower:]')"; \
	printf '{"services":{"redis":{"container_name":"%s-redis"}}}\n' "$$project" > "$$output/compose-output.json"; \
	printf 'Docker artifacts: %s\nOwned Compose project: %s\n' "$$output" "$$project"; \
	trap '$(COMPOSE) -p "$$project" -f docker-compose.yml -f "$$output/compose-output.json" down' EXIT; \
	$(COMPOSE) -p "$$project" -f docker-compose.yml -f "$$output/compose-output.json" \
	  run --rm --pull never --name "$$project-runner" --user "$$(id -u):$$(id -g)" \
	  --volume "$$output/logs:/app/logs" --volume "$$output/reports:/app/reports" \
	  --volume "$$output/tmp:/app/tmp" \
	  --env TMPDIR=/app/tmp --env FRAMEWORK_RESULTS_DIR=/app/reports/results \
	  --env FRAMEWORK_OFFLINE=0 --env COVERAGE_FILE=/app/reports/.coverage \
	  api-tests python -m pytest -o addopts='' --verbose --tb=short --strict-markers \
	  --timeout=60 -p no:cacheprovider --basetemp=/app/tmp/pytest \
	  --junitxml=/app/reports/junit.xml --html=/app/reports/report.html --self-contained-html \
	  --cov=src --cov=config --cov-branch --cov-fail-under=80 \
	  --cov-report=term-missing --cov-report=xml:/app/reports/coverage.xml \
	  --cov-report=html:/app/reports/htmlcov $(1) $(PYTEST_ARGS) 2>&1 | tee "$$output/docker.log"
endef

docker-run: docker-ready ## Run prepared local images with Redis and sandbox output mounts
	$(call run_docker,)

docker-run-parallel: docker-ready ## Run prepared local images with four workers and sandbox outputs
	$(call run_docker,-n 4)

docker-clean: ## Show review guidance; do not delete Docker resources automatically
	@printf '%s\n' 'No Docker resources were deleted.' \
	  'Each docker-run target stops only its unique Compose project on exit.' \
	  'Inspect the recorded project name and Docker labels before removing retained resources.'

pin-base-image: ## Pull BASE_IMAGE and display its digest without changing the Dockerfile
	$(DOCKER) pull "$(BASE_IMAGE)"
	$(DOCKER) inspect --format='{{index .RepoDigests 0}}' "$(BASE_IMAGE)"
	@printf '%s\n' 'Review this digest before updating the Dockerfile.'

audit: require-env ## Audit requirements.txt using the sandbox venv and cache
	@mkdir -p "$(SANDBOX_DIR)/audit-cache" "$(SANDBOX_DIR)/audit-tmp"
	TMPDIR="$(SANDBOX_DIR)/audit-tmp" "$(PYTHON)" -m pip_audit -r requirements.txt --strict --cache-dir "$(SANDBOX_DIR)/audit-cache"

lint: require-env ## Run Ruff without caching and MyPy with its cache in sandbox
	@mkdir -p "$(SANDBOX_DIR)/mypy-cache"
	"$(PYTHON)" -m ruff check --no-cache src config scripts tests/offline tests/fixtures conftest.py
	"$(PYTHON)" -m mypy --cache-dir "$(SANDBOX_DIR)/mypy-cache" src config

clean: ## Show review guidance; preserve retained evidence and existing project files
	@printf '%s\n' 'No files were deleted.' \
	  'Review task-owned outputs before deleting any known disposable artifacts.' \
	  'Keep evidence or uncertain files for review; do not clean other sessions.'
	@printf 'Configured sandbox: %s\n' "$(SANDBOX_DIR)"
