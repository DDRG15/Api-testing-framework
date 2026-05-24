# Enterprise API Testing Framework — Implementation Plan

> Tracking file for the super overhaul. Check each item when done and add the date (YYYY-MM-DD) next to the checkbox.
> Last updated: 2026-05-24

---

## S-Tier — Critical Security (fix before any code review)

- [x] **S1** — `config/settings.py` — Add HTTPS-only validator on `api_base_url` *(2026-05-19)*
- [x] **S2** — `src/client/base_client.py:270` — Add HTTPS guard in `set_auth_token()` *(2026-05-19)*
- [x] **S3** — Add Ruff + MyPy static analysis (via `pyproject.toml` + CI job) *(2026-05-24)*
- [ ] **S4** — Add pre-commit hooks (`.pre-commit-config.yaml`)

---

## A-Tier — High Priority (fix before first CI PR)

- [x] **A1** — Add `pytest-cov` with 80% branch coverage gate *(2026-05-24)*
- [x] **A2** — `conftest.py:533` — Add token TTL expiry check in `_get_cached_teardown_token` *(2026-05-24)*
- [x] **A3** — `src/client/booking_client.py:119` — Replace raw `dict` with `PartialBookingPayload` model on PATCH *(2026-05-19)*
- [ ] **A4** — `.github/workflows/api-tests.yml` — Upload `leaked_resources.txt` as CI artifact
- [ ] **A5** — `requirements.txt` — Remove unused `allure-pytest` (or wire up Allure server)

---

## B-Tier — Next Sprint

- [x] **B1** — `src/utils/data_factory.py:206` — Fix Faker locale `"ar_AA"` → `"ar_EG"` *(2026-05-19)*
- [ ] **B2** — Add `pytest-rerunfailures`; mark canary + SLO tests `@pytest.mark.flaky(reruns=1)`
- [x] **B3** — `src/client/base_client.py:482` — Log warning when response body is truncated at 4096 chars *(2026-05-24)*
- [x] **B4** — `src/client/base_client.py` — Inject `correlation_id` into SLO `AssertionError` and retry exceptions *(2026-05-24)*
- [ ] **B5** — Create `tests/functional/test_auth_edge_cases.py` (invalid creds, bad token, no token)
- [x] **B6** — `tests/functional/test_canary.py` — Remove `CanaryPayload`/`CanaryDates`; use canonical `BookingPayload` *(2026-05-19)*

---

## C-Tier — Backlog (do when needed)

- [ ] **C1** — `tests/performance/locustfile.py` — Locust load baseline (separate `requirements-perf.txt`)
- [ ] **C2** — `k8s/test-job.yaml` — Kubernetes Job manifest (non-root, secret injection)
- [ ] **C3** — `config/settings.py` — Remove dead comment at end of file
- [ ] **C4** — `Makefile` — Update `lint` target from `py_compile` to `ruff check .`
- [ ] **C5** — `docker-compose.yml` — Remove deprecated `version: "3.9"` field

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
| G11 | chore: add .pre-commit-config.yaml + .secrets.baseline | — | pending |
| G12 | ci: add pytest-cov; enforce 80% branch coverage gate | 2026-05-24 | ✅ done |
| G13 | ci: add pytest-rerunfailures; mark flaky tests selectively | — | pending |
| G14 | ci: upload leaked_resources.txt as CI artifact | — | pending |
| G15 | ci: remove allure-pytest; clean Dockerfile/docker-compose | — | pending |
| G16 | test: add auth edge case tests | — | pending |
| G17 | chore: dead comment, docker-compose version, Makefile lint | — | pending |
| G18 | feat: add Locust performance baseline | — | pending |
| G19 | feat: add k8s/test-job.yaml Kubernetes Job manifest | — | pending |
