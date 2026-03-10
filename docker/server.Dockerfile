FROM docker.io/python:3.14-alpine3.23

# copy uv binary from uv image to alpine /bin/
COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /uvx /bin/

WORKDIR /app

# enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# omit development dependencies by default
ENV UV_NO_DEV=1

# cache project dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-workspace

# copy necessary project files
COPY packages/core/ packages/core/
COPY packages/server/ packages/server/
COPY pyproject.toml uv.lock ./

# sync core + server dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen \
      --package core \
      --package server

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Expose the port the server will run on
EXPOSE 8000

# Default command to run the FastAPI server in development mode
# This enables auto-reload for code changes
CMD ["uv", "run", "--package", "server", "fastapi", "dev", "--host", "0.0.0.0", "packages/server/src/server"]
