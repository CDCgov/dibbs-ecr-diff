import boto3
import pytest
from moto import mock_aws


@pytest.fixture(scope="function")
def bucket_name():
    return "ecr-dev-data-repository"


@pytest.fixture(scope="function")
def dynamodb_table_name():
    return "did-eicr-record"


@pytest.fixture(scope="function")
def aws_creds(monkeypatch, dynamodb_table_name):
    """Mocked AWS credentials for integration tests."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("DYNAMODB_TABLE", dynamodb_table_name)


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


@pytest.fixture(scope="function")
def dynamodb_table(aws_creds, dynamodb_table_name):
    with mock_aws():
        dynamodb = boto3.resource("dynamodb")

        # create table
        # based on our local dev env setup in docker/localstack-init.py
        db_table = dynamodb.create_table(
            TableName=dynamodb_table_name,
            AttributeDefinitions=[
                {"AttributeName": "setId", "AttributeType": "S"},
                {"AttributeName": "versionNumber", "AttributeType": "N"},
            ],
            KeySchema=[
                {"AttributeName": "setId", "KeyType": "HASH"},
                {"AttributeName": "versionNumber", "KeyType": "RANGE"},
            ],
            # set to PAY_PER_REQUEST to avoid setting read/write capacity for local environment/testing
            BillingMode="PAY_PER_REQUEST",
        )

        yield db_table


@pytest.fixture(scope="function")
def dynamodb_module(dynamodb_table, monkeypatch):
    # import and monkeypatch our actual dynamo module with the mocked table
    from did_lambda import dynamodb as mod

    monkeypatch.setattr(mod, "db", dynamodb_table)
    return mod
