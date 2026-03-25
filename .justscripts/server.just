set working-directory := "../packages/server"

alias h := _default
alias help := _default

# List all available `server` commands
@_default:
    just --list server

server_init_path    := "src/server/__init__.py"

alias prod := run

# Run FastAPI server in dev mode
dev:
    uv run --package server fastapi dev {{ server_init_path }}

# Run FastAPI server in production mode
run:
    uv run --package server fastapi run {{ server_init_path }}