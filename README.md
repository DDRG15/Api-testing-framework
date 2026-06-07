# Enterprise API Testing Framework

Let's be real: testing a REST API on the happy path is trivial. Testing one at the reliability standards of a Tier-1 financial system—where a dropped packet means real money is lost—is an entirely different beast. I engineered this framework with Python, `pytest`, and a healthy dose of operational paranoia to guarantee one thing: **zero false positives.**

---

## Architecture Overview

Here is the blueprint. Notice the dual-strategy circuit breaker—because relying on a single point of failure is a rookie move.

```text
api-testing-framework/
│
├── .github/
│   └── workflows/
│       └── api-tests.yml         # CI/CD: security-audit → code-quality → build-image → api-tests
│
├── config/
│   └── settings.py               # Pydantic-validated config — enforces HTTPS, fails at startup
│
├── src/
│   ├── client/
│   │   ├── base_client.py        # Core HTTP client: retries, circuit breaker, SLO, CID injection
│   │   └── booking_client.py     # Domain client: typed methods returning Pydantic models
│   ├── models/
│   │   └── booking.py            # API contracts: BookingPayload, PartialBookingPayload, responses
│   └── utils/
│       ├── circuit_breaker.py          # Public interface — selects in-memory or Redis impl
│       ├── circuit_breaker_redis.py    # Distributed Redis circuit breaker with Lua atomicity
│       ├── data_factory.py             # Faker-based synthetic data: realistic, edge-case, unicode
│       └── logger.py                   # Structured JSON logger with secret masking
│
├── tests/
│   ├── functional/
│   │   ├── test_bookings_crud.py       # Full CRUD lifecycle + idempotency + edge cases
│   │   ├── test_canary.py              # Canary probe — smoke+flaky marked, static payload
│   │   └── test_auth_edge_cases.py     # Auth boundary tests: bad creds, invalid token, no token
│   ├── contract/
│   │   └── test_schema_contracts.py    # Schema drift detection tests
│   └── performance/
│       └── locustfile.py               # Locust load baseline (requires requirements-perf.txt)
│
├── k8s/
│   └── test-job.yaml             # Kubernetes Job manifest — non-root, secret injection
│
├── IMPLEMENTATION_PLAN.md        # Overhaul tracking — checkbox per item, date when completed
├── conftest.py                   # Session/function fixtures, TTL-gated teardown token, orphan registry
├── pyproject.toml                # Ruff + MyPy + coverage config (80% branch gate)
├── pytest.ini                    # pytest config: timeout, JUnit/HTML output, coverage flags
├── requirements.txt              # All versions pinned — pip-audit gates every bump
├── requirements-perf.txt         # Locust — isolated so it never enters the CI image
├── .pre-commit-config.yaml       # Ruff + MyPy + detect-secrets hooks
├── .secrets.baseline             # detect-secrets known-safe baseline (empty — zero known secrets)
├── .env.example                  # Template — copy to .env, never commit .env
└── .gitignore
```

---

## Engineering Principles

### Zero False Positives
- Retries use exponential backoff **only** on transient codes (429, 502, 503, 504).
- Logic errors (400, 401, 403, 404) **hard fail immediately** — retrying them is just noise.
- `pytest-randomly` randomizes test order to expose hidden order dependencies.
- `pytest-timeout` provides a global 60s watchdog for hangs outside HTTP calls.
- `pytest-xdist` parallel execution coordinated safely via cross-platform OS locks (`filelock`).
- `pytest-rerunfailures` gives live-API tests one retry before failing — distinguishes a real bug from a BGP hiccup.

### Data Integrity & Idempotency
- All payloads use UUID-derived identifiers — zero collision between parallel runs.
- `created_booking` fixture uses `yield` + `finally` — teardown is unconditional.
- Teardown token cache includes a 1-hour TTL with `time.monotonic()` — expired tokens no longer silently leave orphan records.
- An orphan registry sweeps any resource not cleaned up by its owning test.

### Absolute Observability
- Every log line is a JSON object — parseable by Splunk/Datadog/CloudWatch.
- On failure: URL, method, headers (masked), payload, status, body, elapsed time logged.
- `X-Correlation-ID` injected into every `AssertionError` (SLO breach) and `RetryError` message — greppable in any SIEM without cross-referencing the JSONL log.
- When a response body exceeds 4096 chars, a `response_body_truncated` warning is emitted with `full_length` — operators know exactly what they're not seeing.
- A unique `run_id` is bound to every log line for cross-run filtering.

### Static Analysis & Quality Gates
- **Ruff** (E/W/F/I/B/UP rules) enforced on `src/` and `config/` — in CI and via pre-commit hook.
- **MyPy** (`disallow_untyped_defs`, `warn_return_any`) enforced on `src/` and `config/`.
- **pytest-cov** enforces 80% branch coverage — branch coverage catches resilience paths (circuit open, retry exhausted, SLO breach) that line coverage misses.
- **detect-secrets** pre-commit hook blocks credentials before they reach the remote.

### Graceful Handling & Timeouts
- Every HTTP request has an explicit `(connect_timeout, read_timeout)` tuple.
- Timeout exceptions are caught, duration is logged, test fails clearly.
- Dual-strategy Circuit Breaker (Redis/In-Memory) prevents cascading failures during upstream outages.

### Security — Zero Trust
- No credentials, tokens, or URLs in source code.
- Pydantic `FrameworkSettings` reads exclusively from environment variables.
- `API_BASE_URL` is validated at startup: any non-localhost URL that is not `https://` raises `ValueError` before a single test runs. The auth token is never transmitted over plaintext.
- `set_auth_token()` enforces the same HTTPS check at the client level — belt-and-suspenders against programmatic bypass.
- Sensitive headers (Authorization, Cookie, X-API-Key) are masked in logs.
- SSL verification is architecturally non-negotiable — `verify=False` is impossible.

### Contract Testing
- Every API response is deserialized through a Pydantic model.
- Schema drift (renamed field, wrong type, missing required field) fails immediately.
- `PartialBookingPayload` (`extra="forbid"`, all-optional, `exclude_none=True`) ensures PATCH requests are schema-validated before any HTTP call.
- Separate `contract` test suite distinguishes schema failures from logic failures.

### SLO Enforcement
- Every response is checked against `SLO_RESPONSE_TIME_MS`.
- A 200 that took 5 seconds is treated as a failure, with `correlation_id` in the exception message.

---

## Local Setup

### Option A: Native Python (Windows/macOS/Linux)
Runs the suite locally using the fallback In-Memory circuit breaker. Perfect for rapid development.

```bash
# 1. Clone and enter the repository
git clone <your-repo-url>
cd api-testing-framework

# 2. Create a virtual environment (Don't skip this, trust me)
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
.venv\Scripts\activate          # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment (NEVER commit .env)
cp .env.example .env
# Edit .env with your API values

# 5. Run tests in parallel across all CPU cores
pytest -n auto -v

# 6. (Optional) Install pre-commit hooks
pip install pre-commit && pre-commit install
```

### Option B: Docker Environment (Enterprise CI Parity)
Runs the exact immutable container image used in CI, alongside a Redis instance for the distributed circuit breaker.

```bash
# 1. Configure environment
cp .env.example .env

# 2. Run the full suite with Docker Compose
docker-compose up --build

# 3. Run specific test categories
docker-compose run --rm api-tests pytest -m crud -v
docker-compose run --rm api-tests pytest -m contract -v
```

### Option C: Kubernetes
```bash
# 1. Create the secrets
kubectl create secret generic api-test-secrets \
  --from-literal=API_BASE_URL=https://your-api.internal \
  --from-literal=API_USERNAME=your-username \
  --from-literal=API_PASSWORD=your-password

# 2. Run the Job
kubectl apply -f k8s/test-job.yaml
kubectl logs -f job/api-test-suite
```

### Performance Baseline (Locust)
```bash
pip install -r requirements.txt -r requirements-perf.txt

locust -f tests/performance/locustfile.py \
    --headless --users 30 --spawn-rate 5 --run-time 5m \
    --host https://restful-booker.herokuapp.com
```

---

## CI/CD — GitHub Actions

### Why the API Tests Job Shows a Failure in This Repository

The `API Tests` job in the public CI run will show a failure. This is intentional and expected.

This repository is a portfolio demonstration of the framework's architecture and CI/CD gate design. It is not connected to a live API. The three secrets required to execute the test suite — `API_BASE_URL`, `API_USERNAME`, and `API_PASSWORD` — are deliberately not configured on this public repository.

Every gate that can be validated without live credentials passes:

| Job | Status | Why |
|---|---|---|
| Security Audit (CVE Scan) | Passes | No credentials needed — scans `requirements.txt` |
| Code Quality (Ruff + MyPy) | Passes | No credentials needed — static analysis only |
| Build & Cache Docker Image | Passes | No credentials needed — builds from source |
| API Tests | Fails at credential validation | `API_BASE_URL`, `API_USERNAME`, `API_PASSWORD` not set |

The pipeline fails loudly at the credential validation step with a clear error message — `Missing GitHub Secrets: ['API_BASE_URL', 'API_USERNAME', 'API_PASSWORD']` — which is the correct behavior. A pipeline that silently skips tests and reports green when credentials are absent would be a significantly worse design.

**To run the full suite against a real endpoint:** fork the repository, add the three secrets in `Settings → Secrets and variables → Actions`, and re-run the pipeline. The Restful-Booker public API at `https://restful-booker.herokuapp.com` requires no registration and accepts `admin` / `password123` as credentials.

---

### Required Secrets

| Secret | Required | Description |
|---|---|---|
| `API_BASE_URL` | Yes | Full base URL of the target API |
| `API_USERNAME` | Yes | Auth username |
| `API_PASSWORD` | Yes | Auth password |
| `API_TOKEN` | No | Optional pre-issued token — skips the `/auth` round-trip if set |
| `SSL_CA_BUNDLE` | No | Path to a custom CA bundle for private CAs |

### Pipeline Stages
1. **Security Audit** — `pip-audit` scans all dependencies for CVEs. Nothing proceeds if a vulnerability is found.
2. **Code Quality** — Ruff lint + MyPy type check on `src/` and `config/`. Runs in parallel with Docker build. A type error blocks test execution the same way a CVE does.
3. **Docker Build** — Multi-stage image built and pushed to GHCR with BuildKit layer caching. Image is tagged with the commit SHA for exact traceability.
4. **API Tests** — Full suite runs inside the built image. Secrets are injected as env vars, never written to disk or CLI arguments. Artifacts (JSONL logs, HTML report, JUnit XML, leaked_resources.txt) uploaded unconditionally.
5. **Regression Notification** — On scheduled-run failure, a GitHub Issue is opened automatically with labels `regression`, `automated`, `needs-triage`.

---

## Extending for a Real Financial System

| Area | Extension |
|---|---|
| **Auth** | Replace token auth with OAuth2/mTLS in `booking_client.authenticate()` |
| **Environments** | Add `env`-scoped `FrameworkSettings` subclasses for dev/staging/prod SLOs |
| **Pact** | Export Pydantic models to a Pact broker for consumer-driven contracts |
| **Performance** | Point `locustfile.py` at a staging environment; set SLO thresholds per endpoint |
| **Alerting** | POST the structured JSONL log to a webhook on failure |
| **Scale** | Replace in-memory circuit breaker with Redis-backed impl for multi-node runners |

---

## The War Stories / I Shot Myself in the Foot

Look, I'm not going to sit here and pretend this architecture materialized perfectly out of thin air. Real engineering is messy, and I tripped over my own shoelaces a few times building this. Here is the unfiltered truth about the bugs we squashed so you don't have to:

1. **The "Oops, Global Install" Disaster:** Yeah, I got a bit too fast in the terminal and accidentally ran `pip install -r requirements.txt` directly into my global Windows Python environment because I forgot to activate my virtual environment (`.venv`). It triggered a massive dependency conflict cascade. Lesson learned: always isolate your environment. Always.
2. **The `fcntl` Trap:** While building the `pytest-xdist` parallel execution lock, I tried to be clever and used `fcntl` for process coordination. Guess what? `fcntl` is a Unix-only kernel call. It blew up spectacularly the second I ran it natively on my Windows machine. I had to rip it out and replace it with the cross-platform `filelock` package so it works flawlessly everywhere.
3. **The "Production-Ready" Reality Check:** It hit me hard during debugging: "Production-Ready" doesn't just mean your code runs perfectly on a pristine Linux server inside a Docker container. It means the system is resilient enough that it won't crash when someone clones the repo onto their Windows laptop and runs `pytest` out of the box. Graceful degradation (like falling back to an in-memory circuit breaker when Redis isn't found) is a feature, not an afterthought.

### The "Localhost is a Lie" Reality Check

Let's not kid ourselves: passing 100% of tests using pristine, synthetic `Faker` data in a local sandbox is great, but the real internet is a chaotic, stochastic jungle.

I am not going to insult your intelligence by quoting some arbitrary "expect a 1% variance" metric when moving to production. The unfiltered truth? I don't know the exact failure rate you'll see in the wild, because I haven't pointed this at *your* specific infrastructure yet. It could run flawlessly, or the transition from synthetic data to live traffic could metaphorically blow your arm off.

Here is what actually happens when you leave the deterministic vacuum of local testing:

* **The WAF Wall:** Real-world firewalls (Cloudflare, Akamai) do not care about your `pytest-xdist` parallel execution. If you fire a high-concurrency async battery from a single IP, the WAF will classify you as a DDoS attack and throttle you into the ground.
* **The Legacy DB Trap:** `Faker` generates beautifully chaotic, high-entropy UTF-8 payloads. Your upstream 10-year-old `latin1` database backend might just choke on them and throw a 500 Internal Server Error.
* **The Network Jitter:** Real packets traverse unpredictable BGP hops. Synthetic local packets don't. Your perfectly tuned `read_timeout` settings *will* occasionally get breached simply by the physics of internet routing.

**The SRE Takeaway:** This framework is a precision instrument, but it assumes a baseline of deterministic sanity. If you are pointing this at a live production system for the first time, run a single-threaded Canary Probe with known-good static data first. Do not unleash the full concurrent stochastic battery on day one and act surprised when the pager goes off.
