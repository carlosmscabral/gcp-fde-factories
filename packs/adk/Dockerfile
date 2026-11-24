# Runtime container layer for packs/adk (ADK 2.15.0 + google-agents-cli 1.15.0 + Gemini Enterprise export).
# Pins verified co-installable via `uv pip compile --python-version 3.12`.
ARG CORE_BASE_IMAGE=core-gcp-fde-base:0.4.0
FROM ${CORE_BASE_IMAGE}

USER root
ARG FINAL_USER=scion
ARG ADK_VERSION=2.15.0
ARG AIPLATFORM_VERSION=2.10.0
ARG A2A_SDK_VERSION=1.3.1
ARG AGENTS_CLI_VERSION=1.15.0
ARG PYTEST_VERSION=9.2.0

ENV ADK_FACTORY_DIR=/opt/adk-factory

# Install resolved ADK runtime with [eval,a2a] extras, google-agents-cli, Agent Platform adapter, Vertex AI SDK, and test tools.
RUN uv pip install --python "${VIRTUAL_ENV}/bin/python" --no-cache \
      "google-adk[eval,a2a]==${ADK_VERSION}" \
      "google-cloud-aiplatform==${AIPLATFORM_VERSION}" \
      "google-cloud-agentplatform[agent-engines]==${AIPLATFORM_VERSION}" \
      "fastapi<0.142.0" \
      "a2a-sdk==${A2A_SDK_VERSION}" \
      "google-agents-cli==${AGENTS_CLI_VERSION}" \
      "pytest==${PYTEST_VERSION}"

# Package ADK verification gate, GE exporter, Janitor, and toolchain manifest.
COPY packs/adk/scripts/ "${ADK_FACTORY_DIR}/"
COPY packs/adk/toolchain-manifest.json "${GCP_FDE_DIR}/adk-toolchain-manifest.json"
COPY NOTICE "${ADK_FACTORY_DIR}/NOTICE"
RUN chmod +x "${ADK_FACTORY_DIR}/ge_export.py" "${ADK_FACTORY_DIR}/adk_sandbox_gate.py" \
      "${ADK_FACTORY_DIR}/adk-eval-runner.sh" "${ADK_FACTORY_DIR}/sandbox_janitor.py" \
    && chown -R scion:scion "${GCP_FDE_DIR}" "${ADK_FACTORY_DIR}" \
    && su -s /bin/sh scion -c 'PATH="/opt/gcp-fde/.venv/bin:$PATH" adk --version >/dev/null && PATH="/opt/gcp-fde/.venv/bin:$PATH" adk eval --help >/dev/null && PATH="/opt/gcp-fde/.venv/bin:$PATH" agents-cli --version >/dev/null && PATH="/opt/gcp-fde/.venv/bin:$PATH" python3 /opt/adk-factory/ge_export.py --help >/dev/null'

USER ${FINAL_USER}
