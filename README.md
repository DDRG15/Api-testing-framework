# API Testing Framework

A personal REST API testing toolkit built with Python, pytest, and Pydantic. It checks response contracts, HTTP client resilience, and persisted effects, then preserves evidence for each phase and attempt.

Licensed under the [MIT License](LICENSE). Third-party dependencies retain their own
licenses.

[Explore the interactive architecture](docs/architecture.html): hover to trace connections, click to pin a node, and press Escape to reset. Open the HTML in a browser, or use the [architecture source and component guide](docs/ARCHITECTURE.md).

## Start with the local console

Linux users can run `./api-lab setup`, then `./api-lab start`. The optional
`./api-lab install` adds an application-menu entry. See the
[Linux launcher guide](docs/LINUX_LAUNCHER.md) for dependencies, shutdown and MCP
entrypoints. The launcher uses Python and Node.js; it is not a standalone binary.

Create a sandbox environment and install the core toolchain:

```bash
python3 -m venv ~/sandbox/enterprise-api-testing-framework/venv
source ~/sandbox/enterprise-api-testing-framework/venv/bin/activate
export PYTHONDONTWRITEBYTECODE=1
python -m pip install -r requirements-dev.txt
python scripts/console.py
```

Open the private loopback URL printed by the command. The React console runs
offline checks, compares contracts and evaluates the supplied synthetic sample,
then shows actual results. Node.js 22.12+ and npm are required for the first
frontend build; dependencies, build outputs and evidence stay in sandbox.
These offline checks need no account, API key or `.env`. See the
[console guide](docs/LOCAL_CONSOLE.md).

For your own endpoint, open **Connections** and configure a GET response contract
with optional Bearer/header authentication. Separate OpenAI/Anthropic BYOK forms
check provider catalog authentication. Credentials remain in the server process
for the session; model text generation is not implemented. See
[Connections and editor usage](docs/CONNECTIONS.md). The offline checks still
require no provider key.

To share the open console's Connections profiles with an MCP-compatible host,
run `./api-lab mcp-setup --console --format codex` or `--format claude` on Linux.
For standalone offline operations, run `python scripts/setup_mcp.py` from the
core environment. Both helpers print configuration for you to merge into your
host settings. The optional SDK has its own sandbox venv and does not change
the core contract dependencies. See [MCP setup](docs/MCP.md).

## Execution paths

| Path | Purpose | Dependencies and limits |
|---|---|---|
| Offline | Unit tests, versioned contracts, and controlled failures. | Includes a local HTTP payment lab with SQLite and synthetic data. No Stripe account or external service is required. |
| Live demo | A single-worker canary before CRUD checks against Restful-Booker. | Depends on the public provider and configuration. Its results are separate from the offline path. |
| Configured integration | Functional and contract tests for a Restful-Booker-compatible booking API. | Another API requires compatible endpoints or adapted clients/tests, plus a controlled test environment. |
| Connections | One configured JSON GET response contract, or OpenAI/Anthropic catalog authentication. | Settings and credentials remain in the console process for the session. These checks use the network and do not generate model text or adapt the booking suite. |

The payment lab is a controlled reference system. Passing its tests does not establish the behavior of another billing service, PostgreSQL, or Stripe.

## Local execution

From the project root, create a development environment outside the repository:

```bash
python3 -m venv ~/sandbox/enterprise-api-testing-framework/venv
source ~/sandbox/enterprise-api-testing-framework/venv/bin/activate
export PYTHONDONTWRITEBYTECODE=1
python -m pip install -r requirements.txt
```

Run the offline checks:

```bash
python scripts/run_offline.py
```

The runner writes to `~/sandbox/enterprise-api-testing-framework/runs/<UTC-timestamp>-<id>/`, or to a **new** directory supplied with `--output`. It refuses to reuse an existing directory. Source code, durable tests, and expected contracts remain in the project.

Outputs include `summary.md`, `summary.json`, phase evidence in `results-*.jsonl`, `report.html`, `junit.xml`, `coverage.xml`, and `pytest.log`. `manifest.json` records the revision, working-tree state, Python version, command, exit code, installed dependency versions, and artifact and source hashes. Keep these files together to review what ran.

Select tests after `--`:

```bash
python scripts/run_offline.py -- tests/offline/test_billing_reliability.py
```

Check the contract baseline and selected client defects:

```bash
python scripts/check_contracts.py
python scripts/mutation_check.py
```

Review model changes alongside their snapshot diff. Updating a baseline without examining the change does not validate provider compatibility. Mutation checks use isolated source copies after a passing baseline; their report covers selected defects, not a general mutation score for the whole project.

## External API checks

Prepare configuration from [.env.example](.env.example), using values for a Restful-Booker-compatible test environment:

```bash
cp .env.example .env
# Set API_BASE_URL, API_USERNAME, and API_PASSWORD; do not publish .env.
LIVE_OUTPUT="$HOME/sandbox/enterprise-api-testing-framework/live/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$LIVE_OUTPUT"
export FRAMEWORK_RESULTS_DIR="$LIVE_OUTPUT" LOG_FILE="$LIVE_OUTPUT/http.jsonl"
export PYTHONDONTWRITEBYTECODE=1 TMPDIR="$LIVE_OUTPUT"
python -m pytest -o addopts='' --timeout=60 tests/functional/test_canary.py -n 0 \
  --junitxml="$LIVE_OUTPUT/canary.xml" --html="$LIVE_OUTPUT/canary.html" --self-contained-html
# Continue only if the canary passes.
python -m pytest -o addopts='' --timeout=60 tests/functional tests/contract -n 0 \
  --junitxml="$LIVE_OUTPUT/acceptance.xml" --html="$LIVE_OUTPUT/acceptance.html" --self-contained-html
```

These tests create and delete bookings. The template contains placeholders:
replace the URL, credentials and log path with your test configuration. The
public-demo workflow separately declares its demonstration values. Configure
Redis when parallel workers need shared breaker state. The in-memory breaker
shares state only within its process. See [configuration](docs/CONFIGURATION.md).

These bounded commands clear the general `addopts`; they do not attempt to satisfy the full-suite coverage gate. The configured integration workflow retains its own policy.

## Test history reports

Build a history report from phase-evidence files retained across runs:

```bash
python scripts/build_history_report.py \
  "$HOME/sandbox/enterprise-api-testing-framework/runs/"*/results-*.jsonl \
  --output "$HOME/sandbox/enterprise-api-testing-framework/history/report-$(date -u +%Y%m%dT%H%M%SZ)"
```

The new output directory contains `history.html`, `history.json`, and `history.csv`. The HTML works offline; click a cell to inspect its run, attempts, outcome, and source evidence. The JSON retains source hashes.

Rows separate tests and recorded contexts, including context digest, environment, revision, and contract. Unknown context or unverified chronology stays visible and is not classified across runs. Review classification requires unique timezone-aware `run_started_utc` timestamps. By default, at least 10 comparable pass/fail outcomes and 3 outcome switches make a test a **candidate for human review**; adjust these criteria with `--min-runs` and `--min-switches`. Expected failures do not contribute to those binary outcomes.

A valid history report exits successfully even when it contains past failures: it is a diagnostic report, not a CI quality gate. Empty or malformed input exits with code 2 before creating output. It does not quarantine tests automatically or prove that a recovered rerun was a false positive.

## Structured response evaluation

Evaluate captured responses using the supplied synthetic configuration and JSONL sample:

```bash
python scripts/evaluate_responses.py \
  --config fixtures/evaluation/config.json \
  --input fixtures/evaluation/synthetic_responses.jsonl \
  --output "$HOME/sandbox/enterprise-api-testing-framework/evaluations/sample-$(date -u +%Y%m%dT%H%M%SZ)"
```

The evaluator writes `evaluation.json` and `evaluation.md` to a new directory. It checks the configured JSON Schema and deterministic properties instead of requiring identical response text. Supported invariants compare an ordered numeric range or a total with its parts, using JSON Pointer locations and a configured absolute tolerance. Results are grouped by case, model, and prompt; reports do not include raw response bodies.

The supplied input contains four valid synthetic records for one example case and model, with varied outputs across two prompt versions. The command makes no model calls. Keep the input and configuration alongside the reports for review; this example does not validate a live AI provider. Descriptive nearest-rank p95 requires at least 20 latency observations; smaller groups report no p95. This statistic describes the sample, not a production SLA or confidence guarantee.

Exit code 0 requires nonempty input with every record valid. Invalid records, schema/invariant failures, or an empty corpus return 1. Invalid configuration, unreadable input, or reuse of an output directory returns 2.

## Reliability features

- **Replay-aware retries:** transient failures are evaluated together with method safety. POST and PATCH require explicit replay permission backed by server-side deduplication; a header alone cannot provide idempotency.
- **Circuit breaker:** in-memory behavior for one process and a Redis alternative for shared state. Controlled checks cover retry exhaustion and circuit opening.
- **Versioned contracts:** Pydantic models and JSON Schema snapshots in `fixtures/contracts/`. These are local baselines, not complete OpenAPI or consumer compatibility coverage.
- **Synthetic test data:** Faker and UUID suffixes reduce collisions. Fixtures attempt cleanup and record resources they could not delete.
- **Persistence checks:** the local payment lab exercises duplicate delivery, concurrency, and lost responses after commit. Approved read-only queries check the resulting database state.
- **Per-attempt evidence:** setup, call, and teardown outcomes retain run context and initial failures. HTTP retries and test reruns remain distinct.
- **Diagnostics:** JSON logs include run IDs, correlation IDs, and configured credential-pattern masking. Avoid unnecessary sensitive values in payloads.
- **Bounded latency:** explicit timeouts and per-response thresholds. These assertions do not establish statistical availability or a service-level agreement.

## CI and coverage

| Workflow | Purpose |
|---|---|
| [offline-tests.yml](.github/workflows/offline-tests.yml) | Reproducible checks and artifacts without relying on a public API. |
| [live-demo.yml](.github/workflows/live-demo.yml) | Separate public demo, starting with a canary; external failures remain visible. |
| [api-tests.yml](.github/workflows/api-tests.yml) | Dependency audit, static analysis, and Docker image on every push. The integration tests run on manual dispatch, after you configure the environment secrets. |
| [local-console.yml](.github/workflows/local-console.yml) | Build the locked React frontend and test the optional MCP stdio connection in isolated environments. |

The configured integration validates `API_BASE_URL`, `API_USERNAME`, and `API_PASSWORD` before running. Missing configuration fails explicitly. Workflow files describe intended execution; consult actual runs and artifacts for results.

The general configuration sets an **80% coverage threshold with branch measurement enabled**. It is not a separate 80% branch threshold. The offline path reports coverage with `--cov-fail-under=0`; its narrower scope does not certify the full gate. Reports must retain their command, exclusions, and source context. Real Redis coordination and external providers need separate checks.

The project also includes a Locust baseline in `tests/performance/locustfile.py`, a Dockerfile, and a Job in `k8s/`. These are execution options; their presence alone does not establish scale, performance, or a production deployment.

## Source layout

```text
api-lab                            Linux launcher for the console and MCP setup
assets/                            Application icon
config/settings.py                 Validated configuration
src/client/                        HTTP client and domain adapters
src/control/                       Local operation service and HTTP adapter
src/models/booking.py              Booking models
src/utils/                         Contracts, results, data, breaker, and oracle
tests/unit/                        Unit tests
tests/offline/                     Controlled reliability scenarios
tests/fixtures/                    Reference server and test helpers
tests/functional/                  CRUD, canary, and authentication checks
tests/contract/                    API response contracts
tests/mcp/                         MCP stdio smoke check
tests/performance/                 Locust baseline
fixtures/contracts/                Versioned model schemas
fixtures/evaluation/               Synthetic evaluation configuration and inputs
scripts/                           Execution, reporting, and setup tools
ui/                                React console source and dependency lockfile
docs/                              Architecture, console, Connections, MCP, launcher, and configuration guides
k8s/                               Kubernetes Job manifest
.github/workflows/                 CI workflows
```
