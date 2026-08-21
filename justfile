alias h := default
alias help := default

# List all available commands
default:
    @just --list --list-submodules

[group('structurizr')]
mod arch './.justscripts/structurizr.just'

alias install := sync
alias i := sync

# Download Python dependencies and sync all packages
[group('python')]
sync:
    uv sync --all-packages
    uv run lefthook install

# Run pytest unit tests
[group('python')]
test *ARGS:
    uv run pytest {{ ARGS }}

# Run the local Compose end-to-end test
[group('python')]
e2e:
    uv run pytest -vv e2e/e2e.py

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
    uv run --package cli python packages/cli/src/cli/main.py  {{ ARGS }}
