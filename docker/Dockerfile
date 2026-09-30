# Multi-stage Dockerfile for Lifeline Edge System

# Stage 1: Build Web Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/web
COPY apps/web/package*.json ./
RUN npm install
COPY apps/web/ ./
RUN npm run build

# Stage 2: Runtime Backend
FROM python:3.12-slim AS runner
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY models /app/models
COPY edge /app/edge
COPY data /app/data
COPY scripts /app/scripts
COPY apps /app/apps

# Copy built frontend assets
COPY --from=frontend-builder /app/web/dist /app/apps/web/dist

# Expose API and Web port
EXPOSE 8000

ENV QDRANT_STORAGE_PATH=/app/data/qdrant_storage
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
