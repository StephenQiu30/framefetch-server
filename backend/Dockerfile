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
COPY --link sql ./sql
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    CREATION_CARD_FONT_PATH=/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
    PATH="/app/backend/.venv/bin:${PATH}"
WORKDIR /app/backend

# /work is created private to appuser; a fresh runner_work volume inherits it.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install --no-install-recommends -y \
        ca-certificates ffmpeg libstdc++6 xauth fonts-noto-cjk \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app \
    && install -d -o 10001 -g 10001 -m 0700 /work

COPY --link --from=backend-builder --chown=10001:10001 /app/backend /app/backend
COPY --link --from=node-runtime /usr/local/bin/node /usr/local/bin/node

# The Python lock pins the driver and its exact Chromium revision together.
RUN python -m playwright install --with-deps --no-shell chromium \
    && chmod -R a+rX /opt/playwright \
    && install -d -o 10001 -g 10001 -m 0700 /var/lib/video-browser

# nodriver needs a visible Chromium under Xvfb. Container isolation supplies the
# sandbox boundary; never use a host Chrome executable or Profile.
COPY --link app/workers/runner/wpc-chromium.sh /usr/local/bin/framefetch-wpc-chromium
RUN chmod 0755 /usr/local/bin/framefetch-wpc-chromium

USER appuser
EXPOSE 8111
CMD ["python", "-m", "app.main"]
