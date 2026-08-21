from typing import Any

from e2e.helpers import EICRPair, Uploader

DYNAMODB_TABLE = "e2e-did-eicr-record"


def test_happy_path(uploader: Uploader, dynamodb: Any) -> None:
    uploader.send_manifest("happy-path", EICRPair(1))
