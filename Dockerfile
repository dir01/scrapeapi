# Fast, small image with Chromium dependencies via Playwright
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_CACHE_DIR=/opt/uv-cache \
    UV_LINK_MODE=copy

WORKDIR /app

# System deps first (for Playwright + fonts)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates git \
    libglib2.0-0 libnspr4 libnss3 libdbus-1-3 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libxcb1 libxkbcommon0 libatspi2.0-0 \
    libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
    libgbm1 libcairo2 libpango-1.0-0 libasound2 && \
    rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv

# Install Playwright and Chromium early for better layer caching
RUN --mount=type=cache,target=/opt/uv-cache \
    uv pip install --system "playwright>=1.45.0" && \
    python -m playwright install chromium

# Copy pyproject.toml for app dependencies
COPY pyproject.toml .

# Install remaining Python dependencies from pyproject.toml dependencies list
RUN --mount=type=cache,target=/opt/uv-cache \
    uv pip install --system \
    fastapi==0.111.0 \
    "uvicorn[standard]==0.30.1" \
    "scrapegraphai>=1.15.0,<2.0.0" \
    "pydantic>=2.6,<3" \
    "jsonschema>=4.21,<5"

# Copy application code last for better cache utilization
COPY app ./app

# OCI labels
LABEL org.opencontainers.image.source="https://github.com/dir01/scrapeapi"
LABEL org.opencontainers.image.description="FastAPI service wrapping scrapegraph-ai for HTTP-based web scraping"
LABEL org.opencontainers.image.title="scrapeapi"
LABEL org.opencontainers.image.vendor="dir01"

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
