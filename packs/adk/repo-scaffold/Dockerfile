# Native google-agents-cli (adk_python) container image hardened for non-root execution (ADR-014).
# Serves ADK HTTP (/apps/app, /run_sse), dynamic A2A (/a2a/app), and Agent Engine Playground (/api/reasoning_engine).
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.8.13 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/code/.venv/bin:${PATH}" \
    PORT=8080

WORKDIR /code

COPY pyproject.toml README.md agents-cli-manifest.yaml ge_manifest.json uv.lock* ./
COPY app/ ./app/

RUN if [ -f uv.lock ]; then uv sync --frozen --no-dev; else uv sync --no-dev; fi \
    && useradd --uid 1000 --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /code

ARG AGENT_VERSION=0.1.0
ENV AGENT_VERSION=${AGENT_VERSION}

USER appuser

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn app.fast_api_app:app --host 0.0.0.0 --port ${PORT:-8080}"]
