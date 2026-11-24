# Core FDE factory base container image.
# Supports either python:3.12-slim-bookworm or an upstream Scion harness base (scion-claude / scion-antigravity).
# Packages /opt/gcp-fde/ (0-token Kaizen collector, brownfield scanner, Verdict verifier, and schemas).
ARG BASE_IMAGE=python:3.12-slim-bookworm
FROM ${BASE_IMAGE}

USER root
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GCP_FDE_DIR=/opt/gcp-fde

# Install baseline CLI dependencies without overwriting an already newer git from a Scion base image.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      jq \
    && (command -v git >/dev/null 2>&1 || apt-get install -y --no-install-recommends git) \
    && rm -rf /var/lib/apt/lists/*

# Ensure the non-root scion user (UID 1000) exists when built on top of a plain Debian Python image.
RUN id -u scion >/dev/null 2>&1 || useradd --uid 1000 --create-home --shell /bin/bash scion

# Pin uv installer and core schema validation libraries explicitly.
RUN pip install --no-cache-dir uv==0.6.14 \
    && uv pip install --system --no-cache PyYAML==6.0.2 jsonschema==4.23.0 pytest==9.2.0

# Package reusable Layer 1 0-token tools (Kaizen collector, brownfield scanner, verifier, workarounds, schemas).
COPY core-gcp-fde/scripts/ "${GCP_FDE_DIR}/"
COPY scripts/lib/ "${GCP_FDE_DIR}/scripts/lib/"
COPY scripts/verify-verdict.py "${GCP_FDE_DIR}/verify-verdict.py"
COPY schemas/ "${GCP_FDE_DIR}/schemas/"
COPY WORKAROUNDS.yaml "${GCP_FDE_DIR}/WORKAROUNDS.yaml"
RUN chmod +x "${GCP_FDE_DIR}/kaizen_collect.py" "${GCP_FDE_DIR}/factory_onboard.py" "${GCP_FDE_DIR}/verify-verdict.py" \
    && chown -R scion:scion "${GCP_FDE_DIR}"

USER scion
RUN python3 "${GCP_FDE_DIR}/kaizen_collect.py" --help >/dev/null \
    && python3 "${GCP_FDE_DIR}/factory_onboard.py" --help >/dev/null
