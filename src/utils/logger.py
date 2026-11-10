"""
Structured JSON logging with run and request correlation identifiers.

Configured framework logging emits JSON records at the selected log level.
Processors redact selected header/body credential keys and URL details before
serialization. Review application-specific sensitive fields before sharing logs.
Correlation IDs connect the framework's request events when retained; a complete
upstream trace also requires support and evidence from the target service.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

import structlog
from structlog.types import EventDict, WrappedLogger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_SENSITIVE_HEADER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"^authorization$",
        r"^x-api-key$",
        r"^cookie$",
        r"^set-cookie$",
        r"^x-auth-token$",
        r"^proxy-authorization$",
    ]
]

_MASK = "***REDACTED***"

# Body keys redacted recursively from configured request/response mappings.
# Matching is case-insensitive; unrecognized sensitive fields need separate review.
_SENSITIVE_BODY_KEYS: frozenset[str] = frozenset(
    {"password", "token", "secret", "authorization", "api_key", "apikey"}
)

# One unique ID per test-runner process invocation.
RUN_ID: str = os.environ.get("FRAMEWORK_RUN_ID") or str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Processors
# ---------------------------------------------------------------------------

def _mask_sensitive_headers(
    logger: WrappedLogger, method: str, event_dict: EventDict
) -> EventDict:
    """
    Structlog processor: redacts sensitive HTTP headers in-place.
    Applied to configured request/response header mappings before serialization.
    """
    for key in ("request_headers", "response_headers"):
        headers: dict[str, str] | None = event_dict.get(key)
        if not headers:
            continue
        masked: dict[str, str] = {}
        for header_name, header_value in headers.items():
            if any(p.match(header_name) for p in _SENSITIVE_HEADER_PATTERNS):
                masked[header_name] = _MASK
            else:
                masked[header_name] = header_value
        event_dict[key] = masked
    return event_dict


def _mask_sensitive_body(
    logger: WrappedLogger, method: str, event_dict: EventDict
) -> EventDict:
    """
    Structlog processor: redacts credential fields in request/response bodies.

    Header masking is not enough — the POST /auth body carries the password,
    and a DEBUG-level log of that request would otherwise write the credential
    verbatim into the JSONL sink. Recognized nested credential fields are
    masked here; this is not a general-purpose classifier for sensitive data.
    """
    for key in ("request_body", "response_body"):
        body = event_dict.get(key)
        if isinstance(body, (dict, list)):
            event_dict[key] = _redact_nested(body)
    return event_dict


def _redact_nested(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: (_MASK if str(key).lower() in _SENSITIVE_BODY_KEYS else _redact_nested(item))
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_nested(item) for item in value]
    if isinstance(value, str):
        def safe_url(match: re.Match[str]) -> str:
            try:
                parsed = urlsplit(match.group())
                authority = parsed.netloc.rsplit("@", 1)[-1]
                return urlunsplit((parsed.scheme, authority, parsed.path,
                                   "REDACTED" if parsed.query else "", ""))
            except ValueError:
                return _MASK
        return re.sub(r"\b(?:https?|rediss?|postgres(?:ql)?)://[^\s\"<>]+", safe_url, value)
    return value


def _mask_sensitive_metadata(
    logger: WrappedLogger, method: str, event_dict: EventDict,
) -> EventDict:
    """Remove URL userinfo/query values, including nested metadata and errors."""
    return cast(EventDict, _redact_nested(event_dict))


def _inject_run_id(
    logger: WrappedLogger, method: str, event_dict: EventDict
) -> EventDict:
    """Bind the process-level run_id to every log record."""
    event_dict.setdefault("run_id", RUN_ID)
    return event_dict


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def configure_logging(log_file: str, log_level: str = "INFO") -> None:
    """
    Call once at session startup (conftest.py).
    Configures structlog to emit JSON to both stderr and a JSONL file.
    """
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    # ---- stdlib logging → structlog bridge ----
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=level,
    )

    # File handler: append JSONL for the entire session
    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setLevel(level)
    logging.getLogger().addHandler(file_handler)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _inject_run_id,
        _mask_sensitive_headers,
        _mask_sensitive_body,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _mask_sensitive_metadata,
    ]

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Factory — get a named, pre-bound logger instance."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
