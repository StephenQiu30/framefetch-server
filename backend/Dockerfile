# syntax=docker/dockerfile:1.7

# --- Backend Application Targets ---
FROM node:24-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6 AS node-runtime

FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS backend-builder

ARG UV_VERSION=0.11.32
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=0 \
    UV_LINK_MODE=copy \
    PATH="/app/backend/.venv/bin:/root/.local/bin:${PATH}"
WORKDIR /app/backend

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "uv==${UV_VERSION}"
COPY --link pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY --link app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- Session browser (046): Playwright Chromium, no database or keys ---
FROM backend-builder AS session-browser-builder
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group browser

FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS session-browser

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    PATH="/app/backend/.venv/bin:${PATH}"
WORKDIR /app/backend

COPY --link --from=session-browser-builder /app/backend/.venv /app/backend/.venv
# The pinned playwright package fixes the Chromium build it installs.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && playwright install --with-deps chromium \
    && useradd --create-home --uid 10001 appuser \
    && install -d -o 10001 -g 10001 -m 0700 /profiles \
    && chown -R appuser:appuser /app

COPY --link --from=session-browser-builder --chown=10001:10001 /app/backend/app /app/backend/app

USER appuser
EXPOSE 19300
CMD ["python", "-m", "app.workers.session.browser_app"]

FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/backend/.venv/bin:${PATH}"
WORKDIR /app/backend

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install --no-install-recommends -y \
        ca-certificates ffmpeg libstdc++6 \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

COPY --link --from=backend-builder --chown=10001:10001 /app/backend /app/backend
COPY --link --from=node-runtime /usr/local/bin/node /usr/local/bin/node

USER appuser
EXPOSE 8111
CMD ["python", "-m", "app.main"]
