# Core FDE factory base container image.
# Supports either python:3.12-slim-bookworm (lean CI, FINAL_USER=scion) or an upstream
# Scion harness base (scion-antigravity / scion-claude on Debian Trixie, FINAL_USER=root
# so sciontool init PID 1 can configure metadata interception and drop privileges to scion).
# Packages /opt/gcp-fde/ (0-token Kaizen collector, brownfield scanner, Verdict verifier, schemas).
ARG BASE_IMAGE=python:3.12-slim-bookworm
FROM ghcr.io/astral-sh/uv:0.6.14 AS uv_bin
FROM ${BASE_IMAGE}

USER root
ARG FINAL_USER=scion
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HUSKY=0 \
    GCP_FDE_DIR=/opt/gcp-fde \
    UV_PYTHON_INSTALL_DIR=/opt/gcp-fde/python \
    VIRTUAL_ENV=/opt/gcp-fde/.venv \
    PATH="/opt/gcp-fde/.venv/bin:${PATH}"

# Install baseline CLI dependencies (gh for code-review/Kaizen, git-lfs for LFS smudge/clean checkout)
# without overwriting an already newer git from a Scion base image. Neutralize repo-level Git hooks via
# core.hooksPath=/dev/null (note: LFS smudge/clean filters remain active; run `git lfs push` before `git push`
# when committing new LFS objects). Keep npm scripts enabled by default so pretest/prisma/esbuild builds succeed.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      gh \
      git-lfs \
      jq \
      python3-yaml \
    && (command -v git >/dev/null 2>&1 || apt-get install -y --no-install-recommends git) \
    && git config --system core.hooksPath /dev/null \
    && git lfs install --system --skip-repo \
    && rm -rf /var/lib/apt/lists/*

# Ensure the non-root scion user (UID 1000) exists when built on top of a plain Debian Python image.
RUN id -u scion >/dev/null 2>&1 || useradd --uid 1000 --create-home --shell /bin/bash scion

# Install pinned uv binary without requiring system pip (Debian Trixie Scion bases omit pip).
COPY --from=uv_bin /uv /uvx /usr/local/bin/

# Create a dedicated Python 3.12 venv and install pinned core schema validation libraries.
RUN mkdir -p "${GCP_FDE_DIR}" \
    && uv venv --python 3.12 "${VIRTUAL_ENV}" \
    && uv pip install --python "${VIRTUAL_ENV}/bin/python" --no-cache \
       PyYAML==6.0.2 jsonschema==4.23.0 pytest==9.2.0

# Package reusable Layer 1 0-token tools (Kaizen collector, brownfield scanner, interview bank, verifier, schemas).
COPY core-gcp-fde/scripts/ "${GCP_FDE_DIR}/"
COPY core-gcp-fde/data/ "${GCP_FDE_DIR}/data/"
COPY scripts/lib/ "${GCP_FDE_DIR}/scripts/lib/"
COPY scripts/verify-verdict.py "${GCP_FDE_DIR}/verify-verdict.py"
COPY schemas/ "${GCP_FDE_DIR}/schemas/"
COPY WORKAROUNDS.yaml "${GCP_FDE_DIR}/WORKAROUNDS.yaml"
# Persist /opt/gcp-fde/.venv/bin on PATH across bash AND zsh login/interactive shells so /etc/profile
# and /etc/zsh/zprofile never hide PyYAML/pytest inside Scion tmux panes, zsh, or bash -lc (HC14-F2, HC15-F1).
RUN printf 'export VIRTUAL_ENV=/opt/gcp-fde/.venv\nexport PATH="/opt/gcp-fde/.venv/bin:$PATH"\n' > /etc/profile.d/gcp-fde.sh \
    && chmod 0644 /etc/profile.d/gcp-fde.sh \
    && if [ -f /etc/bash.bashrc ] && ! grep -q '/opt/gcp-fde/.venv/bin' /etc/bash.bashrc; then \
         printf '\n# Persist core-gcp-fde venv on interactive bash shells (HC14-F2)\nexport PATH="/opt/gcp-fde/.venv/bin:$PATH"\n' >> /etc/bash.bashrc; \
       fi \
    && mkdir -p /etc/zsh \
    && for zf in /etc/zsh/zshenv /etc/zsh/zprofile; do \
         if ! grep -qs '/opt/gcp-fde/.venv/bin' "$zf"; then \
           printf '\n# Persist core-gcp-fde venv on zsh shells (HC15-F1)\nexport VIRTUAL_ENV=/opt/gcp-fde/.venv\nexport PATH="/opt/gcp-fde/.venv/bin:$PATH"\n' >> "$zf"; \
         fi; \
       done \
    && chmod 0555 "${GCP_FDE_DIR}/kaizen_collect.py" "${GCP_FDE_DIR}/factory_onboard.py" "${GCP_FDE_DIR}/verify-verdict.py" \
    && chown -R root:root "${GCP_FDE_DIR}" \
    && chmod -R a+rX,go-w "${GCP_FDE_DIR}" \
    && su -l scion -c 'gh --version >/dev/null && git lfs version >/dev/null && python3 -c "import yaml" && pytest --version >/dev/null && python3 /opt/gcp-fde/kaizen_collect.py --help >/dev/null && python3 /opt/gcp-fde/factory_onboard.py --help >/dev/null' \
    && su -s /bin/bash -l scion -c 'python3 -c "import yaml" && pytest --version >/dev/null' \
    && su -s /bin/sh scion -c '/usr/bin/python3 -c "import yaml"'

USER ${FINAL_USER}
