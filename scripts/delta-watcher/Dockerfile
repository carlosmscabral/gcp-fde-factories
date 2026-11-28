# Non-root container image for the Provider-Agnostic External Delta Watcher (Cloud Run).
# Uses Python 3.12 standard library only so runtime dependencies stay zero and auditable.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin watcher

WORKDIR /app
COPY --chown=watcher:watcher adapters /app/adapters
COPY --chown=watcher:watcher intake_models.py intake_filter.py state_store.py hub_notifier.py watcher.py server.py /app/

USER watcher
EXPOSE 8080

CMD ["python3", "/app/server.py"]
