# Stage 1: Build and compile stage
FROM python:3.12-slim AS build

WORKDIR /app

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends git zsh curl && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir pipenv

# Copy dependency files first (for better layer caching)
COPY Pipfile Pipfile.lock ./

# Install dependencies to system Python
RUN pipenv install --deploy --system

# Copy source code
COPY src/ ./src/

# Generate build timestamp (for consistency with other systems)
RUN DATE=$(date +'%Y%m%d-%H%M%S') && \
    echo "${DATE}" > /app/BUILT_AT

# Stage 2: Production stage
FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/agile-learning-institute/stage0_runner"

WORKDIR /opt/stage0/runner

# Install runtime dependencies including git, zsh, and curl (needed for runbook scripts)
RUN apt-get update && \
    apt-get install -y --no-install-recommends git zsh curl && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir pipenv

# Copy dependency files
COPY Pipfile Pipfile.lock ./

# Install production dependencies
# Using --ignore-pipfile to use Pipfile.lock only (avoids Python version check from Pipfile)
RUN pipenv install --system --ignore-pipfile

# Copy compiled code from build stage
COPY --from=build /app/src/ ./src/
COPY --from=build /app/BUILT_AT ./

# Copy documentation files for API explorer
COPY docs/ ./docs/

# Copy runbooks to working directory for packaged deployment
COPY samples/runbooks/ ./runbooks/

# Create /execution non-writable so startup fails unless user mounts a volume over it
RUN mkdir -p /execution && chmod 555 /execution

# Set Environment Variables
ENV PYTHONPATH=/opt/stage0/runner
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV API_PORT=8083
ENV RUNBOOKS_DIR=./runbooks

# Expose the port the app will run on
EXPOSE 8083

# Command to run the application using Gunicorn with exec to forward signals
# Gunicorn will use the app instance from src.server module
CMD exec gunicorn --bind 0.0.0.0:${API_PORT} --workers 2 --worker-class gevent src.server:app
