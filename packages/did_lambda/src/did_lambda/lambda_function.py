"""Ingest manifests delivered through S3 and SQS."""

from typing import TYPE_CHECKING
from urllib.parse import unquote_plus

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.data_classes import (
    S3EventBridgeNotificationEvent,
    SQSEvent,
    event_source,
)
from aws_lambda_powertools.utilities.typing import LambdaContext
from pydantic import ValidationError

from .models import Manifest

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client

DID_OUTPUT_PREFIX = "DIDOutput/"
DID_COMPLETE_PREFIX = "DIDComplete/"

s3: "S3Client" = boto3.client("s3")
logger = Logger()


class InfraError(Exception):
    """Raised for failures that should fail the Lambda, which will trigger an automated SQS retry / DLQ)."""


@event_source(data_class=SQSEvent)
def lambda_handler(event: SQSEvent, _context: LambdaContext) -> dict:
    """Download manifests and the XML objects they reference."""
    raw_records = event.get("Records")
    if not isinstance(raw_records, list) or not raw_records:
        raise InfraError("SQS event has no Records")

    for record in event.records:
        s3_event = S3EventBridgeNotificationEvent(record.json_body)

        bucket = s3_event.detail.bucket.name
        input_key = unquote_plus(s3_event.detail.object.key)
        persistence_id = persistence_id_from_key(input_key)

        manifest = get_manifest(bucket, input_key)

        for entry in manifest.files:
            logger.info(persistence_id)
            logger.info(entry.eicr)

    return {"statusCode": 200, "message": "OK"}


def get_manifest(bucket: str, key: str) -> Manifest:
    """Reads and validates manifest file from S3."""
    try:
        return Manifest.model_validate_json(read_object(bucket, key))
    except ValidationError as exc:
        raise InfraError(f"Invalid manifest s3://{bucket}/{key}") from exc


def read_object(bucket: str, key: str) -> bytes:
    """Generic utility to read object from S3."""
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except Exception as exc:
        raise InfraError(f"S3 get_object failed s3://{bucket}/{key}: {exc}") from exc


def persistence_id_from_key(key: str) -> str:
    """Strip the first S3 key segment (prefix) to leave the persistence_id.

    AIMS form: YYYY/MM/DD/{uuid}
    Example: DIDInput/2026/07/14/19d4812b-fc1d-471a-8872-6d5edd1714ff
    → 2026/07/14/19d4812b-fc1d-471a-8872-6d5edd1714ff
    """
    parts = key.strip("/").split("/", 1)
    if len(parts) != 2 or not parts[1]:
        raise InfraError(f"S3 key has no persistence_id after prefix: {key}")
    return parts[1]
