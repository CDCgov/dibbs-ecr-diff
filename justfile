alias h := default
alias help := default

# List all available commands
default:
    @just --list --list-submodules

# Run commands against the `server` package
[group('server')]
mod server './.justscripts/server.just'

[group('structurizr')]
mod arch './.justscripts/structurizr.just'

alias install := sync
alias i := sync

# Download Python dependencies and sync all packages
[group('python')]
sync:
    uv sync --all-packages

# Run pytest unit tests
[group('python')]
test *ARGS:
    uv run pytest {{ ARGS }}

# Run ruff linter
[group('python')]
check *ARGS:
    uv run ruff check {{ ARGS }}

# Run ruff formatter
[group('python')]
format *ARGS:
    uv run ruff format {{ ARGS }}

# Run ty typechecker
[group('python')]
ty *ARGS:
    uv run ty check {{ ARGS }}

# Runs CLI to manually diff two eCRs
[group('devtools')]
diff *ARGS:
    uv run --package cli python packages/cli/src/cli/main.py