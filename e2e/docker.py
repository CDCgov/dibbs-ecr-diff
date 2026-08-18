"""Docker Compose controls for end-to-end tests."""

import subprocess
from pathlib import Path

E2E_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = E2E_DIR.parent

DOCKER_COMPOSE = (
    "docker",
    "compose",
    "--env-file",
    str(E2E_DIR / ".env.e2e"),
)


def run_compose(*, cmd: str = "up") -> None:
    """Start, reset, or stop the E2E Docker Compose stack."""
    down = [*DOCKER_COMPOSE, "down", "--volumes", "--remove-orphans"]
    up = [*DOCKER_COMPOSE, "up", "--build", "--detach"]

    if cmd == "up":
        commands = [up]
    elif cmd == "clean":
        commands = [down, up]
    elif cmd == "down":
        commands = [down]

    for command in commands:
        subprocess.run(command, cwd=PROJECT_ROOT, check=True)
