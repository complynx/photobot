#############################
# Builder stage
#############################
FROM python:3.11-bookworm AS builder

# Install uv (fast Python package installer)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
ENV UV_CACHE_DIR=/tmp/uv-cache \
	PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1

# (Optional) system build deps kept minimal; Pillow / numpy ship wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
	build-essential \
	&& rm -rf /var/lib/apt/lists/*

# Create virtual environment using uv (ensures reproducible isolated env)
RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy package sources & setup for dependency resolution; then install into venv
WORKDIR /build
COPY setup.py ./
COPY photobot/ photobot/
RUN uv pip install --no-cache-dir . \
 && rm -rf /root/.cache /tmp/uv-cache

#############################
# Final stage
#############################
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	NAME=photobot

# Install minimal runtime libraries (needed by Pillow etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
	libjpeg62-turbo \
	zlib1g \
	libfreetype6 \
	libpng16-16 \
	&& rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Copy application source (after venv for better layer caching when code changes) excluding already copied python package if unchanged
COPY photobot/ photobot/
COPY config/ config/
COPY i18n/ i18n/
COPY templates/ templates/
COPY static/ static/
COPY layers/ layers/
COPY README.md LICENSE ./

RUN chown -R appuser:appuser /app
USER appuser

# Expose actual server port (default 8080 per Config)
EXPOSE 8080

# Healthcheck (simple TCP check to configured port)
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
	CMD python -c "import socket,os,sys; s=socket.socket(); s.settimeout(2); p=int(os.environ.get('SERVER_PORT',8080)); r=s.connect_ex(('127.0.0.1',p)); s.close(); sys.exit(0 if r==0 else 1)" || exit 1

# Default command
CMD ["python", "-m", "photobot.main"]
