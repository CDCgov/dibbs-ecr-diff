"""Ingest manifests delivered through S3 and SQS."""

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.data_classes import SQSEvent, event_source
from aws_lambda_powertools.utilities.typing import LambdaContext
from pydantic import ValidationError
from types_boto3_s3 import S3Client

from .models import Manifest

s3: S3Client = boto3.client("s3")
logger = Logger()


@event_source(data_class=SQSEvent)
def lambda_handler(event: SQSEvent, _context: LambdaContext) -> dict:
    """Download manifests and the XML objects they reference."""
    for sqs_record in event.records:
        for s3_record in sqs_record.decoded_nested_s3_event.records:
            if s3_record.event_name != "ObjectCreated:Put":
                continue

            bucket = s3_record.s3.bucket.name
            manifest_key = s3_record.s3.get_object.key

            # fetch manifest
            try:
                manifest = _get_manifest(bucket, manifest_key)
                for file in manifest.files:
                    logger.info(file)
            except ValidationError:
                logger.error("Invalid manifest file")
                raise

    return {"statusCode": 200, "message": "OK"}


def _get_manifest(bucket: str, key: str) -> Manifest:
    response = s3.get_object(Bucket=bucket, Key=key)
    with response["Body"] as body:
        return Manifest.model_validate_json(body.read())
