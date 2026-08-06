import boto3
import pytest
from moto import mock_aws


@pytest.fixture(scope="function")
def aws_creds(monkeypatch):
    """Mocked AWS credentials for integration tests."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture(scope="function")
def bucket_name():
    return "ecr-dev-data-repository"


@pytest.fixture(scope="function")
def s3_client(aws_creds, bucket_name):
    with mock_aws():
        mock_s3_client = boto3.client("s3", region_name="us-east-1")
        mock_s3_client.create_bucket(Bucket=bucket_name)
        yield mock_s3_client


@pytest.fixture(scope="function")
def s3_module(s3_client, monkeypatch):
    # import and monkeypatch our actual s3 module with the mocked client
    from did_lambda import s3 as mod

    monkeypatch.setattr(mod, "s3", s3_client)
    return mod
