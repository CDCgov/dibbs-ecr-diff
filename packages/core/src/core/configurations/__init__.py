"""Bundled diff configurations."""

from importlib.resources import files

from core.models import Configuration


def load_configuration(filename: str) -> Configuration:
    """Load and validate a bundled configuration by filename."""
    configuration_json = (
        files(__package__).joinpath(filename).read_text(encoding="utf-8")
    )
    return Configuration.model_validate_json(configuration_json)
