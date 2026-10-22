#############################
# Builder stage
#############################
FROM python:3.11.17-bookworm@sha256:18d373e126e39c29c6d38e71e2f19ca66636568318fc95c7849c462b7f9d3d64 AS builder

# Install uv (fast Python package installer)
COPY --from=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff /uv /uvx /usr/local/bin/
ENV UV_CACHE_DIR=/tmp/uv-cache \
	PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1

# (Optional) system build deps kept minimal; Pillow / numpy ship wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
	build-essential ca-certificates \
	&& rm -rf /var/lib/apt/lists/*

# Create an isolated virtual environment.
RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy package sources & setup for dependency resolution; then install into venv
WORKDIR /build
COPY setup.py requirements.txt ./
COPY photobot/ photobot/
RUN uv pip sync --no-cache-dir requirements.txt \
 && uv pip install --no-cache-dir --no-deps . \
 && uv pip check \
 && rm -rf /root/.cache /tmp/uv-cache

#############################
# Final stage
#############################
FROM python:3.11.17-slim-bookworm@sha256:f06d01d4ba3f8ad5af45a3ec87df19c1d317d8e8961edc0fabda61811af6f7cf

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	NAME=photobot

# Install minimal runtime libraries (needed by Pillow etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
	ca-certificates \
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
