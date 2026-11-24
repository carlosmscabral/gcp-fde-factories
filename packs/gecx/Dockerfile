# Runtime container layer for packs/gecx.
# Installs pinned cxas-scrapi==1.11.0, vendors Apache-2.0 cxas-agent-foundry scripts into /opt/gecx-foundry/,
# and copies pack-owned Sandbox scripts into /opt/gecx-factory/.
ARG CORE_BASE_IMAGE=core-gcp-fde-base:0.4.0
FROM ${CORE_BASE_IMAGE}

USER root
ARG CXAS_VERSION=1.11.0
ARG FOUNDRY_COMMIT=f55e877638dfc07879aad4082abc35c34f18359c

ENV GECX_FOUNDRY_DIR=/opt/gecx-foundry \
    GECX_FACTORY_DIR=/opt/gecx-factory

# Install pinned cxas-scrapi into the runtime Python environment.
RUN uv pip install --system --no-cache "cxas-scrapi==${CXAS_VERSION}"

# Vendor unmodified Apache-2.0 cxas-agent-foundry scripts, references, and assets at pinned commit.
COPY NOTICE "${GECX_FOUNDRY_DIR}/NOTICE"
COPY packs/gecx/toolchain-manifest.json "${GCP_FDE_DIR}/gecx-toolchain-manifest.json"
COPY packs/gecx/scripts/ "${GECX_FACTORY_DIR}/scripts/"
RUN mkdir -p /tmp/foundry-fetch "${GECX_FOUNDRY_DIR}" \
    && curl -fsSL "https://github.com/GoogleCloudPlatform/cxas-scrapi/archive/${FOUNDRY_COMMIT}.tar.gz" \
       | tar -xz -C /tmp/foundry-fetch --strip-components=1 \
    && cp -r /tmp/foundry-fetch/.agents/skills/cxas-agent-foundry/scripts "${GECX_FOUNDRY_DIR}/scripts" \
    && cp -r /tmp/foundry-fetch/.agents/skills/cxas-agent-foundry/references "${GECX_FOUNDRY_DIR}/references" \
    && cp -r /tmp/foundry-fetch/.agents/skills/cxas-agent-foundry/assets "${GECX_FOUNDRY_DIR}/assets" \
    && rm -rf /tmp/foundry-fetch \
    && chmod +x "${GECX_FACTORY_DIR}/scripts/"*.sh "${GECX_FACTORY_DIR}/scripts/"*.py \
    && chown -R scion:scion "${GECX_FOUNDRY_DIR}" "${GECX_FACTORY_DIR}"

USER scion
RUN cxas --help >/dev/null \
    && python3 "${GECX_FOUNDRY_DIR}/scripts/gate-check.py" --help >/dev/null
