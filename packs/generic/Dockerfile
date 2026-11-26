# Lean runtime container layer for packs/generic (sw-*).
# Extends core-gcp-fde-base without ADK or CES dependencies. Customer repositories add exact
# language runtimes (Node, Go, Rust, Java, Nx, Playwright) via .factory/Dockerfile.customer.
ARG CORE_BASE_IMAGE=core-gcp-fde-base:0.6.0
FROM ${CORE_BASE_IMAGE}

USER root
ARG FINAL_USER=scion
ENV GENERIC_FACTORY_DIR=/opt/generic-factory

# Package generic verification gate, Cloud Run janitor, eval runner, and toolchain manifest.
# Keep /opt/generic-factory root-owned and read/execute only (0555/0444) so agent containers cannot tamper with gates (M6).
COPY packs/generic/scripts/ "${GENERIC_FACTORY_DIR}/"
COPY packs/generic/toolchain-manifest.json "${GCP_FDE_DIR}/generic-toolchain-manifest.json"
COPY NOTICE "${GENERIC_FACTORY_DIR}/NOTICE"
RUN chmod 0555 "${GENERIC_FACTORY_DIR}/generic_sandbox_gate.py" \
      "${GENERIC_FACTORY_DIR}/sandbox_janitor.py" \
      "${GENERIC_FACTORY_DIR}/generic-eval-runner.sh" \
    && chmod 0444 "${GCP_FDE_DIR}/generic-toolchain-manifest.json" "${GENERIC_FACTORY_DIR}/NOTICE" \
    && chown -R root:root "${GENERIC_FACTORY_DIR}" "${GCP_FDE_DIR}/generic-toolchain-manifest.json" \
    && su -s /bin/sh scion -c 'PATH="/opt/gcp-fde/.venv/bin:$PATH" python3 /opt/generic-factory/generic_sandbox_gate.py --help >/dev/null && PATH="/opt/gcp-fde/.venv/bin:$PATH" python3 /opt/generic-factory/sandbox_janitor.py --help >/dev/null'

USER ${FINAL_USER}
