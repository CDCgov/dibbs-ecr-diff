set working-directory := "../packages/server"

alias h := _default
alias helper := _default

# List all available `server` commands
@_default:
    just --list server

run_server := "uv run --package server"
app_init    := "src/server/__init__.py"

alias prod := run

# Run FastAPI server in dev mode
dev:
    {{ run_server }} fastapi dev {{ app_init }}

# Run FastAPI server in production mode
run:
    {{ run_server }} fastapi run {{ app_init }}