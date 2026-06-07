# Enterprise API Testing Framework — Implementation Plan

> Tracking file for the super overhaul. Check each item when done and add the date (YYYY-MM-DD) next to the checkbox.
> Last updated: 2026-05-24

---

## S-Tier — Critical Security (fix before any code review)

- [x] **S1** — `config/settings.py` — Add HTTPS-only validator on `api_base_url` *(2026-05-19)*
- [x] **S2** — `src/client/base_client.py:270` — Add HTTPS guard in `set_auth_token()` *(2026-05-19)*
- [x] **S3** — Add Ruff + MyPy static analysis (via `pyproject.toml` + CI job) *(2026-05-24)*
- [x] **S4** — Add pre-commit hooks (`.pre-commit-config.yaml`) *(2026-05-24)*

---

## A-Tier — High Priority (fix before first CI PR)

- [x] **A1** — Add `pytest-cov` with 80% branch coverage gate *(2026-05-24)*
- [x] **A2** — `conftest.py:533` — Add token TTL expiry check in `_get_cached_teardown_token` *(2026-05-24)*
- [x] **A3** — `src/client/booking_client.py:119` — Replace raw `dict` with `PartialBookingPayload` model on PATCH *(2026-05-19)*
- [x] **A4** — `.github/workflows/api-tests.yml` — Upload `leaked_resources.txt` as CI artifact *(2026-05-24)*
- [ ] **A5** — `requirements.txt` — Remove unused `allure-pytest` (or wire up Allure server)

---

## B-Tier — Next Sprint

- [x] **B1** — `src/utils/data_factory.py:206` — Fix Faker locale `"ar_AA"` → `"ar_EG"` *(2026-05-19)*
- [x] **B2** — Add `pytest-rerunfailures`; mark canary + SLO tests `@pytest.mark.flaky(reruns=1)` *(2026-05-24)*
- [x] **B3** — `src/client/base_client.py:482` — Log warning when response body is truncated at 4096 chars *(2026-05-24)*
- [x] **B4** — `src/client/base_client.py` — Inject `correlation_id` into SLO `AssertionError` and retry exceptions *(2026-05-24)*
- [x] **B5** — Create `tests/functional/test_auth_edge_cases.py` (invalid creds, bad token, no token) *(2026-05-24)*
- [x] **B6** — `tests/functional/test_canary.py` — Remove `CanaryPayload`/`CanaryDates`; use canonical `BookingPayload` *(2026-05-19)*

---

## C-Tier — Backlog (do when needed)

- [x] **C1** — `tests/performance/locustfile.py` — Locust load baseline (separate `requirements-perf.txt`) *(2026-05-24)*
- [x] **C2** — `k8s/test-job.yaml` — Kubernetes Job manifest (non-root, secret injection) *(2026-05-24)*
- [x] **C3** — `config/settings.py` — Remove dead comment at end of file *(2026-05-24)*
- [x] **C4** — `Makefile` — Update `lint` target from `py_compile` to `ruff check .` *(2026-05-24)*
- [x] **C5** — `docker-compose.yml` — Remove deprecated `version: "3.9"` field *(2026-05-24)*

---

## Commit Log

| Group | Commit Message | Date | Status |
|-------|---------------|------|--------|
| G0 | docs: create IMPLEMENTATION_PLAN.md | 2026-05-18 | ✅ done |
| G1 | fix(security): enforce HTTPS on api_base_url and set_auth_token | 2026-05-19 | ✅ done |
| G2 | fix(models): complete PartialBookingPayload wiring in client and tests | 2026-05-19 | ✅ done |
| G3 | fix(data): correct ar_AA → ar_EG in data_factory | 2026-05-19 | ✅ done |
| G4 | fix(types): lowercase any → Any in test_schema_contracts | 2026-05-19 | ✅ done |
| G5 | fix(observability): log truncation warning; inject CID into exceptions | 2026-05-24 | ✅ done |
| G6 | fix(teardown): add token TTL check | 2026-05-24 | ✅ done |
| G7 | fix(canary): replace CanaryPayload with canonical BookingPayload | 2026-05-19 | ✅ done |
| G8 | chore: add pyproject.toml (Ruff + MyPy + coverage config) | 2026-05-24 | ✅ done |
| G9 | ci: add code-quality job (Ruff + MyPy) to GitHub Actions | 2026-05-24 | ✅ done |
| G10 | ci: add MyPy type-check job | 2026-05-24 | ✅ done |
| G11 | chore: add .pre-commit-config.yaml + .secrets.baseline | 2026-05-24 | ✅ done |
| G12 | ci: add pytest-cov; enforce 80% branch coverage gate | 2026-05-24 | ✅ done |
| G13 | ci: add pytest-rerunfailures; mark flaky tests selectively | 2026-05-24 | ✅ done |
| G14 | ci: upload leaked_resources.txt as CI artifact | 2026-05-24 | ✅ done |
| G15 | ci: remove allure-pytest; clean Dockerfile/docker-compose | — | pending |
| G16 | test: add auth edge case tests | 2026-05-24 | ✅ done |
| G17 | chore: dead comment, docker-compose version, Makefile lint | 2026-05-24 | ✅ done |
| G18 | feat: add Locust performance baseline | 2026-05-24 | ✅ done |
| G19 | feat: add k8s/test-job.yaml Kubernetes Job manifest | 2026-05-24 | ✅ done |

---

## Pre-Flight Audit Remediation (2026-06-06)

A full 6-persona audit (SEC/SRE/SDET/ARCH/DEV/DATA) produced 13 findings; all were resolved.

| ID | Severity | Fix |
|----|----------|-----|
| F1 | HIGH | Auth edge-case tests unpacked `created_booking` as `int`; it yields `tuple[int, BookingPayload]`. Fixed unpack. |
| F2 | HIGH | Log masking covered headers only; `/auth` body password leaked at DEBUG. Added body-field masking processor + unit test. |
| F3 | HIGH | `reraise=True` made `except RetryError` dead code; CID never injected, internal sentinel leaked. Added public `RetriesExhaustedError`. |
| F4 | MED | 5xx raised outside breaker context → breaker never tripped on a degraded upstream. Moved transient raise inside the breaker. |
| F5 | MED | `CircuitBreakerOpenError` mixed `monotonic`/wall-clock → garbage duration in Redis mode. Pass a pre-computed duration per clock domain. |
| F6 | MED | Canary DELETE not in `finally` and unregistered → prod leak on assertion failure. Wrapped in try/finally + orphan registry. |
| F7 | MED | Dockerfile lectured on digest pinning but used a mutable tag. Pinned `python:3.11-slim@sha256:…`. |
| F8 | MED | `pyproject.toml` declared a non-existent build backend → `pip install -e .` broke. Removed the `[build-system]` table. |
| F9 | MED | "Same seed → same data" was false (uuid4/dates unseeded). Scoped the claim to Faker-derived field values. |
| F10 | MED | `admin`/`password123` hardcoded as locustfile fallbacks. Removed; env vars now required. |
| F11 | LOW | HTTPS guard used substring `localhost` match (bypassable). Now exact-host via `urlparse`. |
| F12 | LOW | Teardown auth ignored `API_TOKEN`. Now honours it, matching the session fixture. |
| F13 | LOW | `EXECUTION_GUIDE.md` carried `Co-Authored-By` lines + stale status. Deleted (record lives here). |

Also added an offline `tests/unit/` suite (logger masking, retry exhaustion, breaker trip) that runs without live credentials, and brought all documentation into line with the fixed code.
