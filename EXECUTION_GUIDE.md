# Overhaul Execution Guide — Exact Code Changes per Group

> This file documents the precise changes needed for each commit group.
> Claude can pick up from any group without re-exploring the codebase.
> Cross-reference with IMPLEMENTATION_PLAN.md for status tracking.
>
> Project root: enterprise-api-testing-framework-v4/api-testing-framework/

---

## STATUS SNAPSHOT (2026-05-18)

| Group | Status | Notes |
|-------|--------|-------|
| G0 | ✅ committed | IMPLEMENTATION_PLAN.md created |
| G1 | ✅ committed | HTTPS validator + SecurityError in set_auth_token |
| G2 | 🔴 IN PROGRESS | models done, booking_client partial, test not updated |
| G3–G19 | ⬜ not started | — |

**G2 partial state:** `src/models/booking.py` already has `PartialBookingPayload` added and `ConfigDict` imported. Still needed: update `booking_client.py` PATCH method signature + update `tests/functional/test_bookings_crud.py` PATCH calls.

---

## G2 — Remaining changes (booking_client.py + test)

### File: `src/client/booking_client.py`

**Change 1 — import PartialBookingPayload** (already done if you see it in the import block)
```python
# In the imports block, add PartialBookingPayload:
from src.models.booking import (
    AuthTokenResponse,
    BookingPayload,
    BookingResponse,
    BookingSummary,
    CreateBookingResponse,
    PartialBookingPayload,   # ← ADD THIS
)
```

**Change 2 — type the PATCH method signature and use model_dump**
Find `partial_update_booking` and replace:
```python
# OLD:
def partial_update_booking(
    self, booking_id: int, partial_payload: dict
) -> BookingResponse:
    """PATCH /booking/{id} — partial update. Returns updated booking."""
    response = self._client.patch(
        f"/booking/{booking_id}",
        json=partial_payload,
    )

# NEW:
def partial_update_booking(
    self, booking_id: int, partial_payload: PartialBookingPayload
) -> BookingResponse:
    """PATCH /booking/{id} — partial update. Returns updated booking."""
    response = self._client.patch(
        f"/booking/{booking_id}",
        json=partial_payload.model_dump(mode="json", exclude_none=True),
    )
```

### File: `tests/functional/test_bookings_crud.py`

**Change 1 — add PartialBookingPayload to imports**
```python
# OLD line 40:
from src.models.booking import BookingDates, BookingPayload, BookingResponse

# NEW:
from src.models.booking import BookingDates, BookingPayload, BookingResponse, PartialBookingPayload
```

**Change 2 — update test_patch_updates_only_specified_fields**
```python
# OLD (around line 427):
patch_data = {"totalprice": 9999, "depositpaid": False}
patched = booking_client.partial_update_booking(booking_id, patch_data)

# NEW:
patch_data = PartialBookingPayload(totalprice=9999, depositpaid=False)
patched = booking_client.partial_update_booking(booking_id, patch_data)
```

**Change 3 — update test_patch_additionalneeds_to_null**
```python
# OLD (around line 471):
patch_data = {"additionalneeds": ""}
patched = booking_client.partial_update_booking(booking_id, patch_data)

# NEW:
patch_data = PartialBookingPayload(additionalneeds="")
patched = booking_client.partial_update_booking(booking_id, patch_data)
```

**Commit command for G2:**
```
git add src/models/booking.py src/client/booking_client.py tests/functional/test_bookings_crud.py
git commit -m "fix(models): add PartialBookingPayload; type booking_client PATCH method

- src/models/booking.py: add PartialBookingPayload with all-optional
  fields, extra=forbid, and exclude_none serialization
- src/client/booking_client.py: partial_update_booking now accepts
  PartialBookingPayload instead of raw dict; serializes with
  model_dump(exclude_none=True)
- tests/functional/test_bookings_crud.py: update PATCH tests to
  construct PartialBookingPayload instead of raw dicts

Fixes: A3 from the overhaul plan.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## G3 — Fix Faker locale ar_AA → ar_EG

### File: `src/utils/data_factory.py` (around line 206)

Find and replace:
```python
# OLD:
unicode_faker = Faker(["ja_JP", "zh_CN", "ar_AA", "ru_RU"])

# NEW:
unicode_faker = Faker(["ja_JP", "zh_CN", "ar_EG", "ru_RU"])
```

**Commit command:**
```
git add src/utils/data_factory.py
git commit -m "fix(data): correct ar_AA → ar_EG Faker locale in data_factory

ar_AA is not a valid Faker locale — it silently falls back to en_US,
making the unicode_names() factory generate ASCII instead of Arabic
script. ar_EG (Egyptian Arabic) is the correct valid locale.

Fixes: B1 from the overhaul plan.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## G4 — Fix lowercase `any` type hint

### File: `tests/contract/test_schema_contracts.py`

Search for all occurrences of `: any` (lowercase) and replace with `: Any`.
Also ensure `from typing import Any` is in the imports at the top.

Find these patterns:
```python
# OLD (wherever it appears):
tuple[int, any]
# or
: any

# NEW:
tuple[int, Any]
# or
: Any
```

Add to imports if not present:
```python
from typing import Any
```

**Commit command:**
```
git add tests/contract/test_schema_contracts.py
git commit -m "fix(types): lowercase any → Any in test_schema_contracts

PEP 484: 'any' (lowercase) is a built-in Python function, not a type
hint. The correct type is typing.Any. This would be caught by Ruff
ANN401 / MyPy once static analysis is wired up.

Fixes: part of S3 from the overhaul plan.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## G5 — Observability: Truncation warning + CID in exceptions

### File: `src/client/base_client.py`

**Change 1 — log warning on body truncation**

Find `_safe_response_body` method (around line 480) and replace:
```python
# OLD:
@staticmethod
def _safe_response_body(response: Response) -> str:
    try:
        return response.text[:4096]
    except Exception:
        return "<unreadable response body>"

# NEW:
@staticmethod
def _safe_response_body(response: Response) -> str:
    try:
        body = response.text
        if len(body) > 4096:
            logger.warning(
                "response_body_truncated",
                original_length=len(body),
                truncated_to=4096,
            )
            return body[:4096]
        return body
    except Exception:
        return "<unreadable response body>"
```

**Change 2 — inject correlation_id into SLO AssertionError**

Find the SLO assertion (search for `slo_response_time_ms` and `AssertionError`):
```python
# OLD (something like):
assert elapsed_ms <= settings.slo_response_time_ms, (
    f"SLO breach: {elapsed_ms:.0f}ms > {settings.slo_response_time_ms}ms threshold."
)

# NEW:
assert elapsed_ms <= settings.slo_response_time_ms, (
    f"SLO breach: {elapsed_ms:.0f}ms > {settings.slo_response_time_ms}ms threshold. "
    f"(correlation_id={cid})"
)
```

**Change 3 — inject CID into RetryError re-raise**

Find where `RetryError` is caught and re-raised (search for `except RetryError`):
```python
# OLD (something like):
except RetryError as exc:
    logger.error("all_retries_exhausted", ...)
    raise

# NEW:
except RetryError as exc:
    logger.error("all_retries_exhausted", correlation_id=cid, ...)
    raise RetryError(
        f"All retry attempts exhausted (correlation_id={cid})"
    ) from exc
```

Note: `RetryError` from tenacity requires `retry_state` as argument. The cleanest approach is to wrap:
```python
except RetryError as exc:
    logger.error("all_retries_exhausted", correlation_id=cid, ...)
    raise RuntimeError(
        f"All retry attempts exhausted (correlation_id={cid})"
    ) from exc
```

**Commit command:**
```
git add src/client/base_client.py
git commit -m "fix(observability): log warning on body truncation; inject CID into exceptions

- _safe_response_body: logs response_body_truncated warning with
  original_length when body exceeds 4096 chars
- SLO AssertionError: now includes correlation_id so ops can grep
  the specific request in Datadog/CloudWatch logs
- RetryError re-raise: wraps with RuntimeError containing CID for
  the same traceback traceability

Fixes: B3, B4 from the overhaul plan.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## G6 — Token TTL expiry guard in conftest

### File: `conftest.py`

Find the `_teardown_token_cache` and `_get_cached_teardown_token` section (around line 533).

**Add these module-level constants/variables** near the existing `_teardown_token_cache`:
```python
import time  # add to imports if not present

TOKEN_TTL_SECONDS: int = 3600  # conservative — re-auth after 1 hour
_teardown_token_cache: Optional[str] = None
_teardown_token_obtained_at: Optional[float] = None
```

**Update `_get_cached_teardown_token` function:**
```python
# OLD:
def _get_cached_teardown_token() -> str:
    global _teardown_token_cache
    if not _teardown_token_cache:
        _auth_client = DirectApiClient()
        _booking = BookingClient(_auth_client)
        _teardown_token_cache = _booking.authenticate(
            username=settings.api_username,
            password=settings.api_password,
        )
        _auth_client.close()
    return _teardown_token_cache

# NEW:
def _get_cached_teardown_token() -> str:
    global _teardown_token_cache, _teardown_token_obtained_at
    now = time.monotonic()
    token_is_stale = (
        _teardown_token_cache is None
        or _teardown_token_obtained_at is None
        or (now - _teardown_token_obtained_at) > TOKEN_TTL_SECONDS
    )
    if token_is_stale:
        _auth_client = DirectApiClient()
        _booking = BookingClient(_auth_client)
        _teardown_token_cache = _booking.authenticate(
            username=settings.api_username,
            password=settings.api_password,
        )
        _teardown_token_obtained_at = now
        _auth_client.close()
    return _teardown_token_cache  # type: ignore[return-value]
```

**Commit command:**
```
git add conftest.py
git commit -m "fix(teardown): add token TTL expiry guard in _get_cached_teardown_token

The teardown token cache had no expiry check. If the framework runs
for longer than the API's token TTL, all cleanup DELETE calls silently
return 403 and every booking created after expiry leaks permanently.

Adds TOKEN_TTL_SECONDS=3600 guard: re-authenticates when the cached
token is older than 1 hour. Conservative — Restful-Booker tokens
appear to be long-lived, but the guard protects against any API that
rotates tokens on a session boundary.

Fixes: A2 from the overhaul plan.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## G7 — Fix test_canary.py: replace CanaryPayload with canonical models

### File: `tests/functional/test_canary.py`

Read the full file first. Then:

1. **Remove** the local `CanaryPayload` and `CanaryDates` class definitions entirely.
2. **Add** imports from the canonical locations:
```python
from src.models.booking import BookingDates, BookingPayload
from src.utils.data_factory import BookingDataFactory
```
3. **Replace** any `CanaryPayload(...)` construction with `BookingDataFactory().realistic()` or explicit `BookingPayload(...)` with proper `date` objects.
4. **Add** `@pytest.mark.smoke` to the canary test class/function.
5. **Add** `register_for_cleanup` / `deregister_from_cleanup` calls if the canary creates bookings without using the `created_booking` fixture.

**Commit command:**
```
git add tests/functional/test_canary.py
git commit -m "fix(canary): replace CanaryPayload with canonical BookingPayload

CanaryPayload used str for date fields, bypassing BookingDates
checkout_must_be_after_checkin validation. A canary that sends
checkin='not-a-date' would create invalid bookings without any
Pydantic error. Now uses BookingDataFactory().realistic() which
goes through the full validated model stack.

Also adds @pytest.mark.smoke marker for use with smoke test CI profile.

Fixes: B6 from the overhaul plan.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## G8 — Add pyproject.toml

### File: `pyproject.toml` (NEW at project root)

```toml
[project]
name = "enterprise-api-testing-framework"
version = "4.0.0"
requires-python = ">=3.11"

# ---------------------------------------------------------------------------
# Ruff — linting + formatting (replaces Flake8, isort, pyupgrade)
# ---------------------------------------------------------------------------
[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "S", "UP"]
ignore = [
    "S101",   # assert statements are expected in tests
    "S105",   # hardcoded password detection — false positives on test creds in .env.example
]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S", "ANN"]
"conftest.py" = ["S"]

# ---------------------------------------------------------------------------
# MyPy — strict type checking (scoped to src/ and config/)
# ---------------------------------------------------------------------------
[tool.mypy]
python_version = "3.11"
strict = true
ignore_missing_imports = true
exclude = ["tests/", "conftest.py"]

[[tool.mypy.overrides]]
module = ["structlog.*", "faker.*", "tenacity.*", "redis.*", "filelock.*"]
ignore_missing_imports = true

# ---------------------------------------------------------------------------
# Coverage — branch coverage with 80% minimum gate
# ---------------------------------------------------------------------------
[tool.coverage.run]
source = ["src", "config"]
branch = true
omit = ["tests/*", "conftest.py", "*/__pycache__/*"]

[tool.coverage.report]
fail_under = 80
show_missing = true
skip_covered = false
```

**Commit command:**
```
git add pyproject.toml
git commit -m "chore: add pyproject.toml with Ruff, MyPy, and coverage config

Central config for the three static analysis tools introduced in the
overhaul: Ruff (linting + formatting), MyPy (strict type checking
scoped to src/ and config/), and coverage.py (80% branch gate).

Fixes: S3 (static analysis infrastructure) from the overhaul plan.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## G9-10 — Add code-quality CI job to GitHub Actions

### File: `.github/workflows/api-tests.yml`

Add a new job `code-quality` between `security-audit` and `build-image`. Find the `build-image:` job and insert before it:

```yaml
  code-quality:
    name: "Code Quality (Ruff + MyPy)"
    runs-on: ubuntu-latest
    needs: security-audit
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: "pip"

      - name: Install quality tools
        run: pip install ruff mypy pydantic pydantic-settings structlog types-requests

      - name: Run Ruff lint
        run: ruff check .

      - name: Run Ruff format check
        run: ruff format --check .

      - name: Run MyPy type check
        run: mypy src/ config/ --config-file pyproject.toml
```

Also update `build-image` job's `needs:` line:
```yaml
# OLD:
needs: security-audit

# NEW:
needs: [security-audit, code-quality]
```

**Commit command:**
```
git add .github/workflows/api-tests.yml
git commit -m "ci: add code-quality job (Ruff + MyPy) to GitHub Actions

Adds a new 'code-quality' job that runs after security-audit and
before build-image. Blocks the pipeline on any Ruff lint/format
error or MyPy type violation in src/ and config/.

The job chain is now: security-audit → code-quality → build-image → api-tests

Fixes: S3 from the overhaul plan.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## G11 — Add pre-commit hooks

### File: `.pre-commit-config.yaml` (NEW at project root)

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.4
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks:
      - id: mypy
        additional_dependencies:
          - pydantic
          - pydantic-settings
          - structlog
          - types-requests
        args: [--config-file=pyproject.toml, src/, config/]

  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
        args: [--baseline, .secrets.baseline]
```

### File: `.secrets.baseline` (NEW at project root)

Run locally to generate: `detect-secrets scan > .secrets.baseline`
Or create a minimal baseline manually if detect-secrets is not installed:
```json
{
  "version": "1.4.0",
  "plugins_used": [
    {"name": "ArtifactoryDetector"},
    {"name": "AWSKeyDetector"},
    {"name": "BasicAuthDetector"},
    {"name": "CloudantDetector"},
    {"name": "DiscordBotTokenDetector"},
    {"name": "GitHubTokenDetector"},
    {"name": "HexHighEntropyString", "limit": 3.0},
    {"name": "IbmCloudIamDetector"},
    {"name": "IbmCosHmacDetector"},
    {"name": "JwtTokenDetector"},
    {"name": "KeywordDetector", "keyword_exclude": ""},
    {"name": "MailchimpDetector"},
    {"name": "NpmDetector"},
    {"name": "PrivateKeyDetector"},
    {"name": "SendGridDetector"},
    {"name": "SlackDetector"},
    {"name": "SoftlayerDetector"},
    {"name": "SquareOAuthDetector"},
    {"name": "StripeDetector"},
    {"name": "TwilioKeyDetector"}
  ],
  "filters_used": [
    {"path": "detect_secrets.filters.allowlist.is_line_allowlisted"},
    {"path": "detect_secrets.filters.common.is_ignored_credentials_file"},
    {"path": "detect_secrets.filters.common.is_templated_secret"},
    {"path": "detect_secrets.filters.heuristic.is_indirect_reference"},
    {"path": "detect_secrets.filters.heuristic.is_likely_id_format"},
    {"path": "detect_secrets.filters.heuristic.is_lock_file"},
    {"path": "detect_secrets.filters.heuristic.is_not_alphanumeric_string"},
    {"path": "detect_secrets.filters.heuristic.is_potential_uuid"},
    {"path": "detect_secrets.filters.heuristic.is_prefixed_with_dollar_sign"},
    {"path": "detect_secrets.filters.heuristic.is_sequential_string"},
    {"path": "detect_secrets.filters.heuristic.is_swagger_file"},
    {"path": "detect_secrets.filters.heuristic.is_templated_secret"}
  ],
  "results": {},
  "generated_at": "2026-05-18T00:00:00Z"
}
```

**Commit command:**
```
git add .pre-commit-config.yaml .secrets.baseline
git commit -m "chore: add .pre-commit-config.yaml and .secrets.baseline

Pre-commit hooks: Ruff (lint + format), MyPy (type check), detect-secrets.
All three hooks run automatically before each git commit, preventing
quality regressions from reaching the repo.

To install: pip install pre-commit && pre-commit install

Fixes: S4 from the overhaul plan.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## G12 — Add pytest-cov; enforce 80% branch coverage gate

### File: `requirements.txt`

Add line (keep pinned versions):
```
pytest-cov==5.0.0
```

### File: `pytest.ini`

In the `addopts` line, append:
```
    --cov=src --cov=config --cov-branch --cov-report=term-missing --cov-report=html:reports/coverage
```

### File: `.github/workflows/api-tests.yml`

In the `api-tests` job, after the main test run step, add:
```yaml
      - name: Upload coverage report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: coverage-${{ github.run_id }}
          path: reports/coverage/
          retention-days: 14
```

**Commit command:**
```
git add requirements.txt pytest.ini .github/workflows/api-tests.yml
git commit -m "ci: add pytest-cov; enforce 80% branch coverage gate

- requirements.txt: add pytest-cov==5.0.0
- pytest.ini: add --cov flags to addopts (branch coverage, HTML report)
- GitHub Actions: upload coverage HTML as CI artifact (14-day retention)

Coverage threshold (80% branches) is configured in pyproject.toml
[tool.coverage.report]. Branch coverage is used because the resilience
paths (circuit open, retry exhausted, SLO breach) are branch conditions
invisible to line-only coverage.

Fixes: A1 from the overhaul plan.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## G13 — pytest-rerunfailures; mark flaky tests selectively

### File: `requirements.txt`

Add:
```
pytest-rerunfailures==14.0
```

### File: `tests/functional/test_canary.py`

On the canary production probe test function/class, add:
```python
@pytest.mark.flaky(reruns=1, reruns_delay=2)
```

Do NOT add `--reruns` globally to pytest.ini — only live-API tests get the marker.

**Commit command:**
```
git add requirements.txt tests/functional/test_canary.py
git commit -m "ci: add pytest-rerunfailures; mark canary as flaky(reruns=1)

- requirements.txt: add pytest-rerunfailures==14.0
- test_canary.py: @pytest.mark.flaky(reruns=1, reruns_delay=2) on the
  production canary probe (network-bound, external dependency)

Applied selectively — NOT globally via pytest.ini --reruns, which would
mask real failures in business-logic tests. Only live-API-hitting tests
that can flake on transient network conditions get the marker.

Fixes: B2 from the overhaul plan.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## G14 — Upload leaked_resources.txt as CI artifact

### File: `.github/workflows/api-tests.yml`

In the `api-tests` job, after the existing artifact upload steps, add:
```yaml
      - name: Upload leaked resources file
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: leaked-resources-${{ github.run_id }}
          path: logs/leaked_resources.txt
          retention-days: 90
          if-no-files-found: ignore
```

**Commit command:**
```
git add .github/workflows/api-tests.yml
git commit -m "ci: upload leaked_resources.txt as CI artifact (90-day retention)

logs/leaked_resources.txt is written when teardown DELETE calls fail,
listing booking IDs that must be manually cleaned from the API.
Previously this file was invisible to anyone not SSH'd into the runner.
Now uploaded with if-no-files-found: ignore (no failure if clean run).

Fixes: A4 from the overhaul plan.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## G15 — Remove allure-pytest; clean Dockerfile/docker-compose

### File: `requirements.txt`

Remove this line:
```
allure-pytest==2.13.5
```

### File: `Dockerfile`

Remove any `allure-results` from mkdir commands and VOLUME declarations.
Search for `allure` and remove those lines.

### File: `docker-compose.yml`

Remove any `allure-results` volume mount or service definition.

**Commit command:**
```
git add requirements.txt Dockerfile docker-compose.yml
git commit -m "ci: remove allure-pytest; clean allure-results from Dockerfile

allure-pytest was installed but never published — no Allure server
configured, no generate step in CI. The dependency adds startup
overhead and generates files nothing consumes. pytest-html already
provides self-contained HTML reports for CI artifacts.

If an Allure server becomes available later, re-add the dependency
then along with the allure generate step.

Fixes: A5 from the overhaul plan.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## G16 — Add auth edge case tests

### File: `tests/functional/test_auth_edge_cases.py` (NEW)

```python
"""
tests/functional/test_auth_edge_cases.py
=========================================
Auth edge case tests: invalid credentials, bad token, no token.

The Restful-Booker API returns {"reason": "Bad credentials"} rather than
a proper 401 on bad auth — this quirk is intentionally tested here.
"""
from __future__ import annotations

import pytest
import requests

from src.client.base_client import ApiClient
from src.models.booking import BookingPayload
from src.utils.data_factory import BookingDataFactory
from src.utils.logger import get_logger

logger = get_logger(__name__)


@pytest.mark.smoke
class TestInvalidCredentials:
    def test_bad_password_returns_bad_credentials_reason(self) -> None:
        """POST /auth with wrong password returns reason field, no token."""
        client = ApiClient()
        response = client.post("/auth", json={"username": "admin", "password": "WRONG_PASSWORD"})
        client.close()

        body = response.json()
        assert "reason" in body, (
            f"Expected 'reason' key in bad-auth response, got: {body}"
        )
        assert "token" not in body, (
            f"API returned a token for bad credentials: {body}"
        )
        logger.info("assert_bad_credentials_no_token_passed")


@pytest.mark.smoke
class TestInvalidToken:
    def test_delete_with_invalid_token_returns_403(
        self,
        created_booking: tuple[int, BookingPayload],
    ) -> None:
        """DELETE /booking/{id} with a garbage token returns 403."""
        booking_id, _ = created_booking

        client = ApiClient()
        client.set_auth_token("invalid_token_abc123_not_real")
        response = client.delete(f"/booking/{booking_id}")
        client.close()

        assert response.status_code == 403, (
            f"Expected 403 for invalid token, got {response.status_code}. "
            "Auth guard may not be enforced."
        )
        logger.info("assert_invalid_token_rejected_passed", booking_id=booking_id)


@pytest.mark.smoke
class TestNoToken:
    def test_delete_without_token_returns_403(
        self,
        created_booking: tuple[int, BookingPayload],
    ) -> None:
        """DELETE /booking/{id} with no auth token returns 403."""
        booking_id, _ = created_booking

        client = ApiClient()
        # Explicitly do NOT call set_auth_token
        response = client.delete(f"/booking/{booking_id}")
        client.close()

        assert response.status_code == 403, (
            f"Expected 403 for unauthenticated DELETE, got {response.status_code}. "
            "The auth requirement on DELETE is not enforced."
        )
        logger.info("assert_no_token_rejected_passed", booking_id=booking_id)
```

**Commit command:**
```
git add tests/functional/test_auth_edge_cases.py
git commit -m "test: add auth edge case tests (invalid creds, bad token, no token)

Three new test classes covering auth boundary conditions:
- TestInvalidCredentials: POST /auth with wrong password returns reason
  field (Restful-Booker quirk) and no token
- TestInvalidToken: DELETE with garbage token returns 403
- TestNoToken: DELETE without any token returns 403

All marked @pytest.mark.smoke so they run in the fast pre-commit gate.

Fixes: B5 from the overhaul plan.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## G17 — Housekeeping

### File: `config/settings.py`

Remove the last line (dead comment):
```python
# DELETE this line at the end of the file:
# This line intentionally left to trigger a re-read — settings extended below
```

### File: `docker-compose.yml`

Remove the top-level `version: "3.9"` line (deprecated in Compose v2).

### File: `Makefile`

Find the `lint` target and update:
```makefile
# OLD:
lint:
	python -m py_compile $(shell find . -name "*.py" -not -path "./.git/*")

# NEW:
lint:
	ruff check .
	ruff format --check .
```

**Commit command:**
```
git add config/settings.py docker-compose.yml Makefile
git commit -m "chore: remove dead comment, fix docker-compose version, update Makefile lint

- config/settings.py: remove trailing dead comment (misleading artifact)
- docker-compose.yml: remove deprecated 'version: 3.9' field (Compose v2
  generates warnings and the field is no longer meaningful)
- Makefile: update lint target from py_compile to 'ruff check .' so it
  uses the same linter as CI and pre-commit

Fixes: C3, C4, C5 from the overhaul plan.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## G18 — Add Locust performance baseline

### File: `requirements-perf.txt` (NEW at project root)

```
locust==2.28.0
```

### File: `tests/performance/__init__.py` (NEW, empty)

```python
```

### File: `tests/performance/locustfile.py` (NEW)

```python
"""
tests/performance/locustfile.py
=================================
Locust load test baseline for the booking API.

Reuses BookingClient and BookingDataFactory from the main framework —
no duplication of data models or HTTP logic.

Run locally:
    pip install -r requirements-perf.txt
    locust -f tests/performance/locustfile.py --host=https://restful-booker.herokuapp.com

Or headless (CI-friendly):
    locust -f tests/performance/locustfile.py --host=... --headless \
        -u 10 -r 2 --run-time 60s --html reports/locust_report.html
"""
from __future__ import annotations

import os
from datetime import date, timedelta

from locust import HttpUser, between, task

from src.models.booking import BookingDates, BookingPayload
from src.utils.data_factory import BookingDataFactory


class BookingApiUser(HttpUser):
    wait_time = between(1, 3)
    _token: str = ""

    def on_start(self) -> None:
        response = self.client.post(
            "/auth",
            json={
                "username": os.environ.get("API_USERNAME", "admin"),
                "password": os.environ.get("API_PASSWORD", "password123"),
            },
        )
        self._token = response.json().get("token", "")

    @task(3)
    def list_bookings(self) -> None:
        self.client.get("/booking", name="/booking (list)")

    @task(2)
    def create_and_delete_booking(self) -> None:
        factory = BookingDataFactory()
        payload = factory.realistic()
        data = payload.model_dump(mode="json")

        create_resp = self.client.post("/booking", json=data, name="/booking (create)")
        if create_resp.status_code == 200:
            booking_id = create_resp.json().get("bookingid")
            if booking_id:
                self.client.delete(
                    f"/booking/{booking_id}",
                    headers={"Cookie": f"token={self._token}"},
                    name="/booking/{id} (delete)",
                )

    @task(1)
    def get_booking(self) -> None:
        # Gets a booking by a predictable ID — adjust to a known ID in staging
        self.client.get("/booking/1", name="/booking/{id} (get)")
```

**Add to Makefile:**
```makefile
test-perf:
	locust -f tests/performance/locustfile.py --host=$(API_BASE_URL) \
		--headless -u 10 -r 2 --run-time 60s \
		--html reports/locust_report.html
```

**Commit command:**
```
git add requirements-perf.txt tests/performance/ Makefile
git commit -m "feat: add Locust performance baseline

- requirements-perf.txt: locust==2.28.0 (isolated from main CI deps)
- tests/performance/locustfile.py: 3 task types (list, create+delete,
  get single) using BookingClient models and BookingDataFactory
- Makefile: add test-perf target for headless locust run

Locust chosen over k6 because it is Python-native and can reuse the
same BookingPayload models and data factory as the main test suite.
Not wired into default CI — run manually or in dedicated perf pipeline.

Fixes: C1 from the overhaul plan.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## G19 — Add Kubernetes Job manifest

### File: `k8s/test-job.yaml` (NEW, create k8s/ directory)

```yaml
# Kubernetes Job manifest for running the API test suite as a scheduled job.
# Adjust image tag, namespace, and secret names to match your cluster.
apiVersion: batch/v1
kind: Job
metadata:
  name: api-test-runner
  namespace: testing
  labels:
    app: api-test-runner
    version: "4.0"
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 3600
  template:
    metadata:
      labels:
        app: api-test-runner
    spec:
      restartPolicy: Never
      securityContext:
        runAsNonRoot: true
        runAsUser: 1001
        runAsGroup: 1001
        fsGroup: 1001
      containers:
        - name: api-tests
          image: ghcr.io/ddrg15/enterprise-api-testing-framework/api-test-runner:latest
          imagePullPolicy: Always
          env:
            - name: API_BASE_URL
              valueFrom:
                secretKeyRef:
                  name: api-test-secrets
                  key: api-base-url
            - name: API_USERNAME
              valueFrom:
                secretKeyRef:
                  name: api-test-secrets
                  key: api-username
            - name: API_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: api-test-secrets
                  key: api-password
            - name: REDIS_URL
              valueFrom:
                secretKeyRef:
                  name: api-test-secrets
                  key: redis-url
                  optional: true
            - name: LOG_LEVEL
              value: "INFO"
            - name: SLO_RESPONSE_TIME_MS
              value: "3000"
            - name: RETRY_MAX_ATTEMPTS
              value: "3"
          volumeMounts:
            - name: test-reports
              mountPath: /app/reports
            - name: test-logs
              mountPath: /app/logs
          resources:
            requests:
              memory: "256Mi"
              cpu: "250m"
            limits:
              memory: "512Mi"
              cpu: "500m"
      volumes:
        - name: test-reports
          emptyDir: {}
        - name: test-logs
          emptyDir: {}
```

**Commit command:**
```
git add k8s/
git commit -m "feat: add k8s/test-job.yaml Kubernetes Job manifest

Kubernetes Job for running the API test suite on-cluster.
Non-root security context (uid 1001) matches Dockerfile user.
Secrets injected via secretKeyRef — no credentials in manifest.
ttlSecondsAfterFinished=3600 auto-cleans completed jobs.

Create the required secret:
  kubectl create secret generic api-test-secrets \
    --from-literal=api-base-url=https://... \
    --from-literal=api-username=admin \
    --from-literal=api-password=... \
    -n testing

Fixes: C2 from the overhaul plan.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## IMPLEMENTATION_PLAN.md — Update as you go

After each group is committed, update the Commit Log table in IMPLEMENTATION_PLAN.md:
- Check the checkbox for each completed item (S/A/B/C tier)
- Set the date column to today's date (YYYY-MM-DD)
- Change status from `pending` to `✅ done`

Then commit that update as part of the same group or as a standalone:
```
git add IMPLEMENTATION_PLAN.md
git commit -m "docs: mark G{N} as completed in IMPLEMENTATION_PLAN.md"
```

---

## Quick Reference: Files Changed per Group

| Group | Files |
|-------|-------|
| G0 ✅ | IMPLEMENTATION_PLAN.md (new) |
| G1 ✅ | config/settings.py, src/client/base_client.py |
| G2 🔴 | src/models/booking.py, src/client/booking_client.py, tests/functional/test_bookings_crud.py |
| G3 | src/utils/data_factory.py |
| G4 | tests/contract/test_schema_contracts.py |
| G5 | src/client/base_client.py |
| G6 | conftest.py |
| G7 | tests/functional/test_canary.py |
| G8 | pyproject.toml (new) |
| G9-10 | .github/workflows/api-tests.yml |
| G11 | .pre-commit-config.yaml (new), .secrets.baseline (new) |
| G12 | requirements.txt, pytest.ini, .github/workflows/api-tests.yml |
| G13 | requirements.txt, tests/functional/test_canary.py |
| G14 | .github/workflows/api-tests.yml |
| G15 | requirements.txt, Dockerfile, docker-compose.yml |
| G16 | tests/functional/test_auth_edge_cases.py (new) |
| G17 | config/settings.py, docker-compose.yml, Makefile |
| G18 | requirements-perf.txt (new), tests/performance/ (new), Makefile |
| G19 | k8s/test-job.yaml (new) |
