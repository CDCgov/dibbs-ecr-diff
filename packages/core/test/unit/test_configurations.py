import pytest
from core.configurations import load_configuration


def test_bundled_configuration_is_valid():
    configuration = load_configuration("aphl_baseline.json")

    assert configuration.rules


def test_load_configuration_rejects_unknown_filename():
    with pytest.raises(FileNotFoundError):
        load_configuration("unknown.json")
