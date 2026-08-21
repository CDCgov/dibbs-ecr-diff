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

BUCKET_NAME = "ecr-dev-data-repository"
DYNAMODB_TABLE = "e2e-did-eicr-record"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"


@pytest.fixture(scope="session", autouse=True)
def compose_stack() -> Iterator[None]:
    """Context manager for tests to run against docker compose stack.

    This will automatically wrap e2e test cases (autouse).
    This will run the stack for the duration of the test suite (scope="session")
    """
    run_compose()
    try:
        yield
    finally:
        run_compose(cmd="down")


@pytest.fixture
def s3_resource() -> Any:
    """S3 resource pre-configured to send requests to LocalStack."""
    return boto3.resource(
        "s3",
        endpoint_url=AWS_ENDPOINT_URL,
        region_name=AWS_DEFAULT_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )


@pytest.fixture
def s3(s3_resource: Any) -> Any:
    """S3 client pre-configured to send requests to LocalStack."""
    return s3_resource.meta.client


@pytest.fixture
def dynamodb_resource() -> Any:
    """DynamoDB resource pre-configured for LocalStack."""
    return boto3.resource(
        "dynamodb",
        endpoint_url=AWS_ENDPOINT_URL,
        region_name=AWS_DEFAULT_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )


@pytest.fixture
def dynamodb(dynamodb_resource: Any) -> Any:
    """DynamoDB client pre-configured for LocalStack."""
    return dynamodb_resource.meta.client


@pytest.fixture
def dynamodb_table(dynamodb_resource: Any) -> Any:
    """DynamoDB table used by the e2e test suite."""
    return dynamodb_resource.Table(DYNAMODB_TABLE)


@pytest.fixture
def uploader(s3: Any, dynamodb: Any) -> Uploader:
    """Build an Manifest builder + Uploader. Analog to docker/uploader.html."""
    uploader = Uploader(s3, BUCKET_NAME, ASSETS_DIR)
    uploader.wait_until_ready()

    dynamodb.get_waiter("table_exists").wait(
        TableName=DYNAMODB_TABLE,
        WaiterConfig={"Delay": 1, "MaxAttempts": 30},
    )

    return uploader


@pytest.fixture(autouse=True)
def clean_localstack_state(
    uploader: Uploader, s3_resource: Any, dynamodb_table: Any
) -> None:
    """Empties S3 and DynamoDB before each e2e test."""
    s3_resource.Bucket(uploader.bucket_name).objects.all().delete()

    response = dynamodb_table.scan(
        ProjectionExpression="#set_id, #version_number",
        ExpressionAttributeNames={
            "#set_id": "setId",
            "#version_number": "versionNumber",
        },
    )
    for item in response.get("Items", []):
        dynamodb_table.delete_item(Key=item)
