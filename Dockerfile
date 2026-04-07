# ── Stage 1: build ────────────────────────────────────────────────────────────
# Compiles Python packages that need C extensions and builds the Tailwind CSS.
# Nothing from this stage leaks into the final image.
FROM python:3.11-slim AS builder

WORKDIR /build

# Build-time dependencies only (gcc, dev headers, Node.js).
# These are NOT copied to the final stage.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libmariadb-dev \
    pkg-config \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libwebp-dev \
    libfreetype6-dev \
    liblcms2-dev \
    libopenjp2-7-dev \
    zlib1g-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Node.js (only needed to compile Tailwind CSS)
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages into the user directory so they're easy to copy
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --user -r requirements.txt

# Build Tailwind CSS (output: /build/static/css/output.css)
COPY package*.json tailwind.config.js ./
COPY src/ ./src/
COPY templates/ ./templates/
RUN npm ci --omit=dev && npm run build:css

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
# Lean image containing only what's needed to run the app.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=app.py \
    FLASK_ENV=production \
    PATH="/home/appuser/.local/bin:$PATH"

RUN groupadd -r appuser && useradd -r -g appuser -m appuser

# Runtime libraries only — no compilers, no dev headers
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmariadb3 \
    libjpeg62-turbo \
    libpng16-16 \
    libtiff6 \
    libwebp7 \
    libfreetype6 \
    liblcms2-2 \
    libopenjp2-7 \
    zlib1g \
    # ffmpeg is needed for video-URL pinning (~150MB).
    # Remove this line if you don't pin video URLs.
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Pull compiled Python packages from the builder stage
COPY --from=builder /root/.local /home/appuser/.local

WORKDIR /app

# Copy only the files the app actually needs at runtime
COPY app.py auth_utils.py email_service.py migrate.py VERSION requirements.txt ./
COPY templates/ ./templates/
COPY static/ ./static/
COPY scripts/ ./scripts/
COPY init.sql ./

# Drop in the compiled CSS (overwrites the placeholder if any)
COPY --from=builder /build/static/css/output.css ./static/css/output.css

RUN mkdir -p /app/static/cached_images /app/static/images \
    && chown -R appuser:appuser /app /home/appuser/.local

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["python", "app.py"]
