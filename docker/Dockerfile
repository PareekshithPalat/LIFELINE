# Multi-stage Dockerfile for the Lifeline edge node

# Stage 1: web console
FROM node:20-alpine AS frontend-builder
WORKDIR /app/web
COPY apps/web/package*.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

# Stage 2: API + Qdrant Edge runtime
FROM python:3.12-slim AS runner
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    LIFELINE_DATA_DIR=/app/data \
    FASTEMBED_CACHE_PATH=/opt/lifeline/models

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY models /app/models
COPY edge /app/edge
COPY data/trusted_protocols.json data/default_personal.json data/retrieval_config.json /app/data/
COPY scripts /app/scripts
COPY apps/api /app/apps/api
COPY --from=frontend-builder /app/web/dist /app/apps/web/dist

# Bake the embedding model into the image so the node works with no network at all.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/opt/lifeline/models')"

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/system/health')"
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
