"""Ingest manifests delivered through S3 and SQS."""

from typing import TYPE_CHECKING

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.data_classes import (
    S3EventBridgeNotificationEvent,
    event_source,
)
from aws_lambda_powertools.utilities.typing import LambdaContext

from .models import Manifest

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client

s3: "S3Client" = boto3.client("s3")
logger = Logger()


@event_source(data_class=S3EventBridgeNotificationEvent)
def lambda_handler(
    event: S3EventBridgeNotificationEvent, _context: LambdaContext
) -> dict:
    """Download manifests and the XML objects they reference."""
    bucket_name = event.detail.bucket.name
    file_key = event.detail.object.key

    print(bucket_name)
    print(file_key)
    # for sqs_record in event.records:
    #     # Powertools parses the outer SQS event separately from its nested body.
    #     s3_event = S3EventBridgeNotificationEvent(sqs_record.json_body)
    #     if s3_event.detail_type != "Object Created":
    #         continue

    #     bucket = s3_event.detail.bucket.name
    #     manifest_key = s3_event.detail.object.key

    #     # fetch manifest
    #     try:
    #         manifest = _get_manifest(bucket, manifest_key)
    #         for file in manifest.files:
    #             logger.info(file)
    #     except ValidationError:
    #         logger.error("Invalid manifest file")
    #         raise

    return {"statusCode": 200, "message": "OK"}


def _get_manifest(bucket: str, key: str) -> Manifest:
    response = s3.get_object(Bucket=bucket, Key=key)
    with response["Body"] as body:
        return Manifest.model_validate_json(body.read())
