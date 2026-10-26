# ==============================================================================
# ARGOS WORKS - Production Container Image
# Multi-platform Linux container (amd64 / arm64)
# ==============================================================================
FROM python:3.12-slim

# Set environment defaults
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PORT=8080 \
    HOST=0.0.0.0 \
    TZ=Asia/Seoul

WORKDIR /app

# Install runtime utilities (curl for container healthcheck, tzdata for timezone, gosu for safe privilege drop, postgresql-client for pg_dump/pg_restore)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    curl \
    gosu \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies from lockfile
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

# Copy application source code
COPY server/ ./server/
COPY web/ ./web/
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Create non-root user for security
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app -s /sbin/nologin appuser

# Pre-create data and backup directories and set permissions
RUN mkdir -p /app/data /app/data/backups /app/data/attachments /app/data/templates /app/logs && \
    chown -R appuser:appgroup /app

# Declare volume for persistent data
VOLUME ["/app/data"]

EXPOSE 8080

# Built-in Container Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/api/health || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Start ARGOS WORKS server
CMD ["python", "server/main.py"]
