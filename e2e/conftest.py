"""Fixtures for local e2e tests."""

import os
from collections.abc import Iterator
from typing import Any

import boto3
import pytest

from e2e.docker import run_compose

AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "test")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "test")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture(scope="session", autouse=True)
def compose_stack() -> Iterator[None]:
    """Run the E2E Compose stack for the test session."""
    run_compose()
    try:
        yield
    finally:
        run_compose(cmd="down")


@pytest.fixture
def s3() -> Any:
    """Return a LocalStack S3 client."""
    return boto3.client(
        "s3",
        endpoint_url=AWS_ENDPOINT_URL,
        region_name=AWS_DEFAULT_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )


@pytest.fixture
def dynamodb() -> Any:
    """Return a LocalStack DynamoDB client."""
    return boto3.client(
        "dynamodb",
        endpoint_url=AWS_ENDPOINT_URL,
        region_name=AWS_DEFAULT_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )
