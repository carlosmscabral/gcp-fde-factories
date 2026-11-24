# Core FDE factory base container image.
# Installs uv, lightweight JSON/YAML tooling, and packages /opt/gcp-fde/ (0-token Kaizen collector and onboard scanner).
ARG BASE_IMAGE=python:3.12-slim-bookworm
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GCP_FDE_DIR=/opt/gcp-fde

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      git \
      jq \
    && rm -rf /var/lib/apt/lists/*

# Pin uv installer and core schema validation libraries explicitly.
RUN pip install --no-cache-dir uv==0.6.14 \
    && uv pip install --system --no-cache PyYAML==6.0.2 jsonschema==4.23.0

# Package reusable Layer 1 0-token tools (Kaizen collector, brownfield scanner, shared libs, and schemas).
COPY core-gcp-fde/scripts/ "${GCP_FDE_DIR}/"
COPY scripts/lib/ "${GCP_FDE_DIR}/scripts/lib/"
COPY schemas/ "${GCP_FDE_DIR}/schemas/"
RUN chmod +x "${GCP_FDE_DIR}/kaizen_collect.py" "${GCP_FDE_DIR}/factory_onboard.py"
