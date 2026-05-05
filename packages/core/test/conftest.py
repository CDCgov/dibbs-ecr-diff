import json
from pathlib import Path

import pytest

TEST_DIR = Path(__file__).parent
ASSETS_DIR = TEST_DIR / "assets"


@pytest.fixture
def sample_rule_configuration_json() -> dict:
    with open(ASSETS_DIR / "sample_rule_config.json") as file:
        return json.load(file)
