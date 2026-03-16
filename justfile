# List all available commands
default:
    @just --list --list-submodules

# Run commands against the `server` package
mod server 'packages/server'

# Run commands against the `cli` package
mod cli 'packages/cli'