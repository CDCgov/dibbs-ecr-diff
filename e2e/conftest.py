"""Fixtures for local e2e tests."""

import os
from collections.abc import Iterator
from hashlib import sha256
from itertools import count
from pathlib import Path
from uuid import UUID

import boto3
import pytest
from syrupy import SnapshotAssertion
from syrupy.extensions.single_file import SingleFileAmberSnapshotExtension
from types_boto3_dynamodb import DynamoDBClient
from types_boto3_dynamodb.service_resource import DynamoDBServiceResource, Table
from types_boto3_s3 import S3Client
from types_boto3_s3.service_resource import S3ServiceResource

from e2e.docker import run_compose
from e2e.helpers import Uploader

AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "test")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "test")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

BUCKET_NAME = "ecr-dev-data-repository"
DYNAMODB_TABLE = "e2e-did-eicr-record"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Configure syrupy to use one snapshot file per assertion.

    See: https://syrupy-project.github.io/syrupy/#built-in-extensions
    """
    return snapshot.use_extension(SingleFileAmberSnapshotExtension)


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
def s3_resource() -> S3ServiceResource:
    """S3 resource pre-configured to send requests to LocalStack."""
    return boto3.resource(
        "s3",
        endpoint_url=AWS_ENDPOINT_URL,
        region_name=AWS_DEFAULT_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )


@pytest.fixture
def s3(s3_resource: S3ServiceResource) -> S3Client:
    """S3 client pre-configured to send requests to LocalStack."""
    return s3_resource.meta.client


@pytest.fixture
def dynamodb_resource() -> DynamoDBServiceResource:
    """DynamoDB resource pre-configured for LocalStack."""
    return boto3.resource(
        "dynamodb",
        endpoint_url=AWS_ENDPOINT_URL,
        region_name=AWS_DEFAULT_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )


@pytest.fixture
def dynamodb(dynamodb_resource: DynamoDBServiceResource) -> DynamoDBClient:
    """DynamoDB client pre-configured for LocalStack."""
    return dynamodb_resource.meta.client


@pytest.fixture
def dynamodb_table(dynamodb_resource: DynamoDBServiceResource) -> Table:
    """DynamoDB table used by the e2e test suite."""
    return dynamodb_resource.Table(DYNAMODB_TABLE)


@pytest.fixture
def uploader(
    s3: S3Client,
    dynamodb: DynamoDBClient,
    request: pytest.FixtureRequest,
) -> Uploader:
    """Build an Manifest builder + Uploader. Analog to docker/uploader.html."""
    # keep track of persistence_id factory calls to generate deterministic persitence_id
    # this ensures snapshots assertions are consistent
    persistence_id_calls = count()

    def build_persistence_id() -> str:
        seed = f"{request.node.nodeid}:{next(persistence_id_calls)}".encode()
        seed_bytes = sha256(seed).digest()[:16]
        uuid = UUID(bytes=seed_bytes, version=4)
        return f"2026/08/24/{uuid}"

    uploader = Uploader(
        s3,
        BUCKET_NAME,
        ASSETS_DIR,
        persistence_id_factory=build_persistence_id,
    )
    uploader.wait_until_ready()

    dynamodb.get_waiter("table_exists").wait(
        TableName=DYNAMODB_TABLE,
        WaiterConfig={"Delay": 1, "MaxAttempts": 30},
    )

    return uploader


@pytest.fixture(autouse=True)
def clean_localstack_state(
    uploader: Uploader, s3_resource: S3ServiceResource, dynamodb_table: Table
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
