# Stage 1: Builder
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install build dependencies for wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libmariadb-dev-compat \
    libmariadb-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and build wheels
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip wheel --no-cache-dir -r requirements.txt -w /wheels

# Stage 2: Runtime
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libmariadb-dev-compat \
    libmariadb-dev \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built wheels and install
COPY --from=builder /wheels /wheels
RUN pip install --no-cache /wheels/*

# Copy app code
COPY . .

# Create writable runtime folders and startup script permissions
RUN mkdir -p /app/media /app/migrations && chmod +x /app/start.sh

# Add non-root user with a fixed UID/GID to match docker-compose runtime user mapping.
RUN groupadd -g 1003 fastapiuser && useradd -m -u 1003 -g 1003 fastapiuser
RUN chown -R fastapiuser:fastapiuser /app

# Switch to non-root user
USER fastapiuser

EXPOSE 8000

# Start the app
CMD ["/app/start.sh"]
