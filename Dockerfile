# ==============================================================================
# ARGOS WORKS - Multi-Stage Production Container (Zero Python Source Leak)
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Builder (Compile Python server into native Linux binary via Nuitka)
# ------------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# Install compilation tools (gcc, g++, ccache, patchelf, libpq-dev)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    ccache \
    patchelf \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies and compilation tools
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && \
    pip install --no-cache-dir nuitka ordered-set zstandard

# Copy application code for compilation
COPY server/ ./server/
COPY web/ ./web/
COPY VERSION ./VERSION

# Compile server/main.py into standalone Linux native binary
RUN python -m nuitka \
    --standalone \
    --assume-yes-for-downloads \
    --low-memory \
    --jobs=2 \
    --lto=no \
    --output-dir=/build/dist \
    --output-filename=argos-works \
    --remove-output \
    --include-data-dir=/build/web=web \
    --include-data-files=/build/server/schema.sql=schema.sql \
    --include-data-files=/build/server/schema.postgres.sql=schema.postgres.sql \
    --include-data-files=/build/VERSION=VERSION \
    --product-name="ARGOS WORKS" \
    --file-description="ARGOS WORKS" \
    --include-module=app_paths \
    --include-module=config \
    --include-module=db \
    --include-module=handler \
    --include-module=router \
    --include-module=wsgi \
    --include-module=module_gate \
    --include-module=middleware_security \
    --include-package=handlers \
    --include-package=services \
    --include-package=utils \
    --nofollow-import-to=gunicorn \
    --nofollow-import-to=pytest \
    --nofollow-import-to=tkinter \
    --nofollow-import-to=setuptools \
    --nofollow-import-to=pip \
    /build/server/main.py

# ------------------------------------------------------------------------------
# Stage 2: Production Runtime (Clean image with ZERO .py source files)
# ------------------------------------------------------------------------------
FROM python:3.12-slim

ENV PORT=8080 \
    HOST=0.0.0.0 \
    TZ=Asia/Seoul

WORKDIR /app

# Install runtime utilities (curl for healthcheck, tzdata, gosu, postgresql-client)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    curl \
    gosu \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy ONLY compiled standalone binary distribution from builder stage
COPY --from=builder /build/dist/main.dist/ /app/
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh /app/argos-works

# Create non-root user for security
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app -s /sbin/nologin appuser

# Pre-create data directories and set permissions
RUN mkdir -p /app/data /app/data/backups /app/data/attachments /app/data/templates /app/logs && \
    chown -R appuser:appgroup /app

VOLUME ["/app/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/api/health || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["/app/argos-works"]
