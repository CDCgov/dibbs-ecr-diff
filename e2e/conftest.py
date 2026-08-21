"""Fixtures for local e2e tests."""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
import pytest

from e2e.docker import run_compose
from e2e.helpers import Uploader

AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "test")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "test")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
BUCKET_NAME = "ecr-dev-data-repository"
DYNAMODB_TABLE = "e2e-did-eicr-record"


@pytest.fixture(scope="session", autouse=True)
def compose_stack() -> Iterator[None]:
    """Context manager for tests to run against docker compose stack.

    Note: `autouse=True` means this will automatically wrap e2e test cases.
    """
    run_compose()
    try:
        yield
    finally:
        run_compose(cmd="down")


@pytest.fixture
def s3() -> Any:
    """S3 client pre-configured to send requests to LocalStack."""
    return boto3.client(
        "s3",
        endpoint_url=AWS_ENDPOINT_URL,
        region_name=AWS_DEFAULT_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )


@pytest.fixture
def dynamodb() -> Any:
    """DynamoDB client pre-configured for LocalStack."""
    return boto3.client(
        "dynamodb",
        endpoint_url=AWS_ENDPOINT_URL,
        region_name=AWS_DEFAULT_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )


@pytest.fixture
def uploader(s3: Any, dynamodb: Any) -> Uploader:
    """Build an Manifest build + Uploader. Analog to docker/uploader.html."""
    uploader = Uploader(s3, BUCKET_NAME, ASSETS_DIR)
    uploader.wait_until_ready()

    dynamodb.get_waiter("table_exists").wait(
        TableName=DYNAMODB_TABLE,
        WaiterConfig={"Delay": 1, "MaxAttempts": 5},
    )

    return uploader
