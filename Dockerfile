# ---- STAGE 1: Builder ----
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Configure uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Disable Python downloads, because we want to use the system interpreter
# across both images.
ENV UV_PYTHON_DOWNLOADS=0

# Install build-time system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libgdal-dev \
    python3-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev

COPY . .

# ---- STAGE 2: Final Image ----
# Use a final image without uv
FROM python:3.13-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Install only run-time system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    libgdal-dev \
    gdal-bin \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for security
RUN groupadd -r django-user && useradd -r -g django-user django-user

WORKDIR /app

# Copy the application from the builder
COPY --from=builder --chown=django-user:django-user /app /app

# Switch to the non-root user
USER django-user

# Expose the port the app runs on
EXPOSE 8000

CMD ["gunicorn", "FishQueryPlatform.asgi:application", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--workers", "4"]
