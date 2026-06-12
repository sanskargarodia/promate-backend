# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    # Keep the venv OUTSIDE /app so a bind-mount of the repo (dev compose) can't
    # shadow it with the host's platform-specific .venv.
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# uv (fast, reproducible installs)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Dependency layer (cached unless pyproject/lock change).
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project

# App layer.
COPY . .

# Non-root.
RUN useradd -m appuser && chown -R appuser:appuser /app /opt/venv
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
