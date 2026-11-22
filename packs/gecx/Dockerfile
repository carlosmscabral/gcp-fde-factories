# Runtime container layer for packs/gecx.
# Installs pinned cxas-scrapi==1.11.0 (from wheelhouse if present) and vendors unmodified
# cxas-agent-foundry scripts, references, and assets (Apache-2.0) into /opt/gecx-foundry/.
ARG CORE_BASE_IMAGE=core-gcp-fde-base:0.1.0
FROM ${CORE_BASE_IMAGE}

ARG CXAS_VERSION=1.11.0
ARG FOUNDRY_COMMIT=f55e877638dfc07879aad4082abc35c34f18359c

ENV GECX_FOUNDRY_DIR=/opt/gecx-foundry

# Install pinned cxas-scrapi into the runtime Python environment.
RUN uv pip install --system --no-cache "cxas-scrapi==${CXAS_VERSION}"

# Vendor unmodified Apache-2.0 cxas-agent-foundry scripts, references, and assets at pinned commit.
RUN mkdir -p /tmp/foundry-fetch "${GECX_FOUNDRY_DIR}" \
    && curl -fsSL "https://github.com/GoogleCloudPlatform/cxas-scrapi/archive/${FOUNDRY_COMMIT}.tar.gz" \
       | tar -xz -C /tmp/foundry-fetch --strip-components=1 \
    && cp -r /tmp/foundry-fetch/.agents/skills/cxas-agent-foundry/scripts "${GECX_FOUNDRY_DIR}/scripts" \
    && cp -r /tmp/foundry-fetch/.agents/skills/cxas-agent-foundry/references "${GECX_FOUNDRY_DIR}/references" \
    && cp -r /tmp/foundry-fetch/.agents/skills/cxas-agent-foundry/assets "${GECX_FOUNDRY_DIR}/assets" \
    && cp /tmp/foundry-fetch/LICENSE "${GECX_FOUNDRY_DIR}/LICENSE" \
    && rm -rf /tmp/foundry-fetch

RUN cxas --help >/dev/null \
    && python3 "${GECX_FOUNDRY_DIR}/scripts/gate-check.py" --help >/dev/null
