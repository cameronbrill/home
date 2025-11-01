FROM python:3.13.9-alpine AS builder

COPY --from=node:25.1.0-alpine /usr/local/bin/node /usr/local/bin/node
RUN apk add --no-cache curl bash ca-certificates git npm

ENV MISE_DATA_DIR="/mise"
ENV MISE_CONFIG_DIR="/mise"
ENV MISE_CACHE_DIR="/mise/cache"
ENV MISE_INSTALL_PATH="/usr/local/bin/mise"
ENV PATH="/mise/shims:$PATH"

RUN curl https://mise.run | sh

COPY mise.toml mise.toml

RUN mise trust .
RUN mise install "npm:@infisical/cli"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:3.13.9-alpine

COPY --from=node:25.1.0-alpine /usr/local/bin/node /usr/local/bin/node
RUN apk add --no-cache curl bash ca-certificates npm

WORKDIR /app

COPY --from=builder /mise /mise
COPY --from=builder /app/.venv /app/.venv

COPY core/ ./core/
COPY entrypoint.sh ./

RUN chmod +x entrypoint.sh

ENV PATH="/app/.venv/bin:/usr/local/bin:/mise/shims:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Health check - the app doesn't expose a port but we can check if process is running
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD ps aux | grep -v grep | grep -q "python.*main.py" || exit 1

ENTRYPOINT ["./entrypoint.sh"]
