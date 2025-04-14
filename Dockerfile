# Use a Python image with uv pre-installed
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build

# Install the project into `/app`
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Install the project's dependencies using the lockfile and settings
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Then, add the rest of the project source code and install it
# Installing separately from its dependencies allows optimal layer caching
ADD . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:3.13-slim-bookworm AS runtime

# Install packages required for the project
RUN apt-get update && apt-get install --no-install-recommends -y \
    curl \
    docker.io \
    docker-compose \
    rclone \
    && apt-get clean

# Copy the installed dependencies from the build stage
COPY --from=build /app /app

# Install the project into `/app`
WORKDIR /app

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

HEALTHCHECK --start-period=5s --interval=30s --timeout=5s CMD curl -f http://localhost/public/health

#ENV FLASK_APP=shard_core
EXPOSE 80
CMD ["fastapi", "run", "--port", "80", "shard_core/app.py"]
