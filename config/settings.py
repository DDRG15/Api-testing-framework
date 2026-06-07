"""
config/settings.py
==================
Single source of truth for all framework configuration.

Loads from environment variables (populated by .env locally and
GitHub Secrets in CI). Fails immediately at import time if any
required variable is absent — no silent misconfigurations.

Design principle: "Fail loud at startup, never fail silently mid-test."
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env only if it exists (local dev). In CI, vars are injected directly.
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=False)


class FrameworkSettings(BaseSettings):
    """
    All settings are sourced from environment variables.
    Pydantic validates types and raises a clear error manifest
    if anything is missing or malformed — before any test runs.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Target API
    # -------------------------------------------------------------------------
    api_base_url: str = Field(
        ...,
        description="Base URL of the API under test. No trailing slash.",
    )
    api_version: str = Field(
        default="v1",
        description="API version string injected into paths if needed.",
    )

    # -------------------------------------------------------------------------
    # Authentication — never hardcoded, always injected
    # -------------------------------------------------------------------------
    api_username: str = Field(..., description="API authentication username.")
    api_password: str = Field(..., description="API authentication password.")
    api_token: str | None = Field(
        default=None,
        description="Bearer token. If None, framework will attempt to fetch one.",
    )

    # -------------------------------------------------------------------------
    # TLS / SSL
    # -------------------------------------------------------------------------
    ssl_ca_bundle: str | None = Field(
        default=None,
        description=(
            "Absolute path to a CA bundle file. "
            "If None, certifi's default bundle is used. "
            "SSL verification is ALWAYS enabled — this field only controls which CA."
        ),
    )

    # -------------------------------------------------------------------------
    # Timeouts (seconds)
    # -------------------------------------------------------------------------
    request_connect_timeout: float = Field(default=5.0, gt=0)
    request_read_timeout: float = Field(default=15.0, gt=0)

    # -------------------------------------------------------------------------
    # Retry policy
    # -------------------------------------------------------------------------
    retry_max_attempts: int = Field(default=3, ge=1, le=10)
    retry_base_delay_seconds: float = Field(default=1.0, gt=0)
    retry_max_delay_seconds: float = Field(default=30.0, gt=0)

    # -------------------------------------------------------------------------
    # SLO enforcement
    # -------------------------------------------------------------------------
    slo_response_time_ms: int = Field(
        default=3000,
        gt=0,
        description="Hard-fail threshold in milliseconds. Any response slower than "
        "this is treated as an SLO breach and fails the test.",
    )

    # -------------------------------------------------------------------------
    # Circuit breaker
    # -------------------------------------------------------------------------
    circuit_breaker_failure_threshold: int = Field(default=5, ge=1)
    circuit_breaker_recovery_timeout_seconds: int = Field(default=60, ge=5)

    # -------------------------------------------------------------------------
    # Redis (optional — required for pytest-xdist distributed circuit breaker)
    # -------------------------------------------------------------------------
    redis_url: str | None = Field(
        default=None,
        description=(
            "Redis connection URL for distributed circuit breaker state. "
            "Required when running pytest-xdist (-n auto). "
            "Example: redis://localhost:6379/0. "
            "If None, an in-memory circuit breaker is used (single-process only)."
        ),
    )

    # -------------------------------------------------------------------------
    # Observability
    # -------------------------------------------------------------------------
    log_level: str = Field(default="INFO")
    log_file: str = Field(default="logs/test_run.jsonl")

    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------
    @field_validator("api_base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("api_base_url")
    @classmethod
    def enforce_https(cls, v: str) -> str:
        # Exact host match — a substring test ("localhost" in v) would let
        # http://localhost.attacker.example bypass the HTTPS requirement and
        # transmit the token in plaintext to an attacker-controlled host.
        host = (urlparse(v).hostname or "").lower()
        is_local = host in {"localhost", "127.0.0.1", "::1"}
        if not is_local and not v.startswith("https://"):
            raise ValueError(
                f"API_BASE_URL must use HTTPS to prevent auth tokens from travelling "
                f"in plaintext. Got: '{v}'. "
                "Use https:// in production. http:// is only permitted for localhost."
            )
        return v

    @field_validator("ssl_ca_bundle")
    @classmethod
    def validate_ca_bundle_path(cls, v: str | None) -> str | None:
        if v and not Path(v).is_file():
            raise ValueError(
                f"SSL_CA_BUNDLE points to non-existent file: '{v}'. "
                "Refusing to start with broken TLS configuration."
            )
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}, got '{v}'")
        return upper

    @model_validator(mode="after")
    def validate_timeout_relationship(self) -> FrameworkSettings:
        if self.request_connect_timeout >= self.request_read_timeout:
            raise ValueError(
                "REQUEST_CONNECT_TIMEOUT must be less than REQUEST_READ_TIMEOUT. "
                f"Got connect={self.request_connect_timeout}s, "
                f"read={self.request_read_timeout}s."
            )
        return self

    # -------------------------------------------------------------------------
    # Derived helpers
    # -------------------------------------------------------------------------
    @property
    def timeout_tuple(self) -> tuple[float, float]:
        """Returns (connect_timeout, read_timeout) as used by requests."""
        return (self.request_connect_timeout, self.request_read_timeout)

    @property
    def ssl_verify(self) -> str | bool:
        """
        Returns the value to pass to requests' `verify` parameter.
        Always truthy — disabling SSL verification is architecturally forbidden.
        """
        return self.ssl_ca_bundle if self.ssl_ca_bundle else True


# ---------------------------------------------------------------------------
# Module-level singleton. Fails hard at import if configuration is invalid.
# ---------------------------------------------------------------------------
try:
    settings = FrameworkSettings()  # type: ignore[call-arg]
except ValidationError as exc:
    # Narrowed to ValidationError so a genuine config problem gets this clear
    # message, while an unrelated bug (e.g. an AttributeError) surfaces normally
    # instead of being mislabelled "CONFIGURATION ERROR".
    raise SystemExit(
        "\n"
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║         FRAMEWORK STARTUP FAILURE — CONFIGURATION ERROR      ║\n"
        "╚══════════════════════════════════════════════════════════════╝\n"
        f"{exc}\n\n"
        "Action required: Copy .env.example → .env and fill in all required values.\n"
        "In CI: Ensure all required GitHub Secrets are configured.\n"
    ) from exc
