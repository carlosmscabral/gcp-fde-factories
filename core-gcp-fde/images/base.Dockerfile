# Core FDE factory base container image.
# Adds only uv and lightweight JSON/YAML tooling on top of a digest-pinned base image.
ARG BASE_IMAGE=python:3.12-slim-bookworm
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      git \
      jq \
    && rm -rf /var/lib/apt/lists/*

# Pin uv installer version explicitly during Phase 1b mirror build.
RUN pip install --no-cache-dir uv==0.6.14
