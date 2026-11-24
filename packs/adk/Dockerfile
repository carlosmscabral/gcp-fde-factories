# Runtime container layer for packs/adk (ADK + Vertex AI Agent Engine + Gemini Enterprise export).
# Inherits /opt/gcp-fde/ (0-token Kaizen collector and brownfield scanner) from core-gcp-fde-base.
ARG CORE_BASE_IMAGE=core-gcp-fde-base:0.4.0
FROM ${CORE_BASE_IMAGE}

ARG ADK_VERSION=1.25.0
ARG AIPLATFORM_VERSION=1.84.0
ARG CLOUDPICKLE_VERSION=3.1.1

ENV ADK_FACTORY_DIR=/opt/adk-factory

# Install pinned ADK runtime, Vertex AI SDK, and offline test libraries.
RUN uv pip install --system --no-cache \
      "google-adk==${ADK_VERSION}" \
      "google-cloud-aiplatform==${AIPLATFORM_VERSION}" \
      "cloudpickle==${CLOUDPICKLE_VERSION}" \
      "pytest==8.3.5"

# Package ADK verification gate, Gemini Enterprise exporter, and pack toolchain manifest.
COPY packs/adk/scripts/ "${ADK_FACTORY_DIR}/"
COPY packs/adk/toolchain-manifest.json "${GCP_FDE_DIR}/adk-toolchain-manifest.json"
COPY NOTICE "${ADK_FACTORY_DIR}/NOTICE"
RUN chmod +x "${ADK_FACTORY_DIR}/ge_export.py" "${ADK_FACTORY_DIR}/adk_sandbox_gate.py" \
      "${ADK_FACTORY_DIR}/adk-eval-runner.sh" "${ADK_FACTORY_DIR}/sandbox_janitor.py" \
    && python3 "${ADK_FACTORY_DIR}/ge_export.py" --help >/dev/null
