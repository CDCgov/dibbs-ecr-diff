# List all available commands
default:
    @just --list --list-submodules

# Run commands against the `server` package
mod server 'packages/server'

# Run commands against the `cli` package
mod cli 'packages/cli'

# Run pytest unit tests
test *ARGS:
    uv run pytest {{ ARGS }}

# Run ruff linter
check *ARGS:
    uv run ruff check {{ ARGS }}

# Run ty typechecker
ty *ARGS:
    uv run ty check {{ ARGS }}