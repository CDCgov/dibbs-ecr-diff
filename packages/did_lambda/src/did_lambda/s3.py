"""S3 operations for the Difference in Docs Lambda."""

from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    IncompleteReadError,
    ReadTimeoutError,
    ResponseStreamingError,
)
from lxml import etree

from .utils import InfraError

if TYPE_CHECKING:
    from botocore.response import StreamingBody
    from types_boto3_s3 import S3Client

s3: "S3Client" = boto3.client("s3")
parser = etree.XMLParser(remove_blank_text=True, huge_tree=True)


def _parse_xml(source: "StreamingBody") -> etree._ElementTree:
    """Parse XML from an S3 streaming body."""
    return etree.parse(source, parser)


def _get_object_body(bucket: str, key: str) -> "StreamingBody":
    """Get an object's streaming body from S3."""
    try:
        return s3.get_object(Bucket=bucket, Key=key)["Body"]
    except (ClientError, BotoCoreError):
        raise InfraError(f"S3 get_object failed s3://{bucket}/{key}") from None


def get_object(bucket: str, key: str) -> bytes:
    """Get an object from S3."""
    body = _get_object_body(bucket, key)
    try:
        return body.read()
    except BotoCoreError:
        raise InfraError(f"S3 get_object failed s3://{bucket}/{key}") from None
    finally:
        body.close()


def get_object_xml_tree(bucket: str, key: str) -> etree._ElementTree:
    """Parse an XML object directly from its S3 stream."""
    body = _get_object_body(bucket, key)
    try:
        return _parse_xml(body)
    except (IncompleteReadError, ResponseStreamingError, ReadTimeoutError) as exc:
        raise InfraError(f"Failed to read S3 body s3://{bucket}/{key}") from exc
    finally:
        body.close()


def put_object(bucket: str, key: str, data: bytes) -> None:
    """Put an object in S3."""
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=data)
    except (ClientError, BotoCoreError):
        raise InfraError(f"S3 put_object failed s3://{bucket}/{key}") from None
