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
    up = [
        *DOCKER_COMPOSE,
        "up",
        "did_lambda",
        "localstack",
        "sqs-poller",
        "--build",
        "--detach",
        "--wait",
    ]

    if cmd == "down":
        print("docker services shuttin down...")
        commands = [down]
    else:
        print("docker services starting...")
        commands = [up]

    for command in commands:
        subprocess.run(command, cwd=PROJECT_ROOT, stdout=subprocess.DEVNULL, check=True)
