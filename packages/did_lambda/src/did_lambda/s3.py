"""S3 operations for the Difference in Docs Lambda."""

from typing import TYPE_CHECKING

import boto3

from .utils import InfraError

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client

s3: "S3Client" = boto3.client("s3")


def get_object(bucket: str, key: str) -> bytes:
    """Get an object from S3."""
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except Exception as exc:
        raise InfraError(f"S3 get_object failed s3://{bucket}/{key}: {exc}") from exc


def put_object(bucket: str, key: str, data: bytes) -> None:
    """Put an object in S3."""
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=data)
    except Exception as exc:
        raise InfraError(f"S3 put_object failed s3://{bucket}/{key}: {exc}") from exc
