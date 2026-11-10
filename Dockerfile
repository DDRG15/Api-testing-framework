# =============================================================================
# Dockerfile — Enterprise API Testing Framework
#
# ─── FIX 3: Non-Deterministic Build Hardening ────────────────────────────────
#
# REMOVED: apt-get upgrade -y
#   WHY: `apt-get upgrade` pulls whatever package versions are current at
#   build time. A broken upstream Debian package will fail your CI pipeline
#   even if you changed zero lines of code. This is a reproducibility failure.
#
#   Base-image updates and installed-package updates both need review.
#   When a base-image issue is identified, review a replacement digest
#   and rebuild. This file does not implement a scheduled image scan.
#
# ADDED: SHA256 digest pin
#   The base image is pinned to an exact content-addressable digest.
#   `python:3.11-slim` is a mutable tag — it changes when Python pushes a
#   new patch release. The same tag resolves to a different image tomorrow.
#   A digest selects a content-addressed base-image reference. Platform
#   selection, apt repositories and resolved dependencies still affect builds.
#
# HOW TO UPDATE THE PIN (run this before bumping):
#   make pin-base-image
#   # or manually:
#   docker pull python:3.11-slim
#   docker inspect python:3.11-slim --format='{{index .RepoDigests 0}}'
#   # Replace the sha256:... below with the new digest.
#
# IMAGE UPDATE GUIDANCE (not an implemented automation):
#   1. Inspect the base image and installed packages with a chosen scanner.
#   2. Review a replacement digest and dependency updates when needed.
#   3. Build and test the resulting image before adopting it.
#   The existing Python dependency audit does not validate this image.
#
# CURRENT PIN:
#   python:3.11-slim @ sha256:a3ab0b96...e49ac0 (pinned 2026-06-06)
#   Re-pin monthly or when a CVE is found. See Makefile target `pin-base-image`.
# =============================================================================

# Pin the base-image reference; this alone does not make builds deterministic.
# To update: run `make pin-base-image` and replace the digest below.
# Review digest updates explicitly; a mutable tag can select a different
# base image on a later build.
FROM python:3.11-slim@sha256:a3ab0b966bc4e91546a033e22093cb840908979487a9fc0e6e38295747e49ac0 AS base

# ─── Metadata labels ───────────────────────────────────────────────────────
LABEL org.opencontainers.image.description="Enterprise API Testing Framework" \
      org.opencontainers.image.base.name="python:3.11-slim" \
      org.opencontainers.image.source="https://github.com/your-org/api-testing-framework"

# ─── System packages: install ONLY what is needed, nothing more ────────────
# We do NOT run apt-get upgrade. Security patching is handled by updating
# the base image digest (see header comment above). Running upgrade here:
#   1. Breaks build reproducibility (package versions are non-deterministic)
#   2. Can pull in broken packages from upstream mirrors
#   3. Is NOT a substitute for a proper base image update workflow
#
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /tmp/* /var/tmp/*


# =============================================================================
# Dependency installation stage
# Separated from the runtime stage so that:
#   - Source code changes don't bust the pip cache layer
#   - Only installed packages (not build tools) reach the final image
# =============================================================================
FROM base AS deps

WORKDIR /install

# Copy only the requirements file. Docker caches this layer until the file
# changes — a test code change does NOT re-run pip install.
COPY requirements.txt .

RUN pip install --upgrade pip --no-cache-dir \
    && pip install --no-cache-dir -r requirements.txt


# =============================================================================
# Runtime stage — the image that actually runs tests
# =============================================================================
FROM base AS runtime

# ─── Non-root user ───────────────────────────────────────────────────────────
# This image selects uid/gid 1001 for its runtime process.
# Cluster admission rules and host volume permissions need separate review.
RUN groupadd --gid 1001 testrunner \
    && useradd --uid 1001 --gid testrunner \
               --shell /bin/bash \
               --create-home \
               testrunner

WORKDIR /app

# Copy installed Python packages from the deps stage (no re-install)
COPY --from=deps /usr/local/lib/python3.11/site-packages \
                 /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy application source, owned by the non-root user
COPY --chown=testrunner:testrunner . .

# Create output directories with correct ownership BEFORE switching users
RUN mkdir -p logs reports allure-results \
    && chown -R testrunner:testrunner logs reports allure-results

# Switch to non-root user for all subsequent operations
USER testrunner

# Declare output directories as volumes (docker-compose bind-mounts these)
VOLUME ["/app/logs", "/app/reports"]

# ─── Health check ────────────────────────────────────────────────────────────
# Checks selected Python imports before reporting container health.
# It does not contact the target API or validate every runtime dependency.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c \
        "import pytest, requests, pydantic, structlog, tenacity, faker; print('OK')" \
    || exit 1

# ─── Default command ─────────────────────────────────────────────────────────
# Override in docker-compose or CI: pytest -m smoke, pytest -m crud, etc.
CMD ["python", "-m", "pytest", "--tb=short", "-v"]
