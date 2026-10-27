# One container: the FastAPI backend serves the API, the WebSocket and the built web app.
# Deployed with fly.toml; runs anywhere with a volume at /data.

FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./

WORKDIR /app
COPY config.yaml ./
COPY sim/ sim/
COPY docs/sim_results.json docs/learning_curve.json docs/
COPY --from=web /web/dist frontend/dist

ENV FRONTEND_DIST=/app/frontend/dist \
    VENT_DATA_DIR=/data \
    PYTHONPATH=/app/backend:/app
EXPOSE 8080
CMD ["/app/backend/.venv/bin/uvicorn", "app.main:app", "--app-dir", "/app/backend", \
     "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
