FROM docker.io/python:3.14-slim-trixie AS base

# Setup a non-root user
RUN groupadd --system --gid 999 nonroot \
 && useradd --system --gid 999 --uid 999 --create-home nonroot

# copy uv binary from uv image to path
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /uvx /bin/

WORKDIR /app

# disable python installation downloads (should use system installation)
ENV UV_PYTHON_DOWNLOADS=0

# compile bytecode for faster start-times
ENV UV_COMPILE_BYTECODE=1

# add executables to path
ENV PATH="/app/.venv/bin:$PATH"

# cache layer of project dependencies w/o workspace members + dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen \
      --no-install-workspace \
      --no-dev

# copy necessary project files
COPY packages/core/ packages/core/
COPY packages/server/ packages/server/
COPY pyproject.toml uv.lock ./

# Expose the port the server will run on
EXPOSE 8000

FROM base AS production

# sync core + server dependencies w/o dev dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --no-dev --package server

USER nonroot
CMD ["fastapi", "run", "packages/server/src/server", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS development

# sync core + server dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package server

USER nonroot
# run the FastAPI server in development mode
CMD ["fastapi", "dev", "packages/server/src/server", "--host", "0.0.0.0", "--port", "8000"]
