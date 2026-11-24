# Opinionated Dockerfile-first container image for ADK agents (Agent Engine BYOC / Cloud Run A2A / GKE).
# Compatible with `agents-cli deploy --deployment-target agent_runtime|cloud_run|gke`.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY agent/ /app/agent/
COPY ge_manifest.json /app/ge_manifest.json

RUN useradd --uid 1000 --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080
CMD ["sh", "-c", "adk api_server --host 0.0.0.0 --port ${PORT} --a2a /app"]
