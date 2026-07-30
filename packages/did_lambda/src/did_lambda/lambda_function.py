"""Ingest manifests delivered through S3 and SQS."""

import os
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

from .models import DIDCompleteManifest, DIDInputManifest, DIDOutputFile

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client

DID_OUTPUT_PREFIX = os.environ.get("DID_OUTPUT_PREFIX", "DIDOutput/")
DID_COMPLETE_PREFIX = os.environ.get("DID_COMPLETE_PREFIX", "DIDComplete/")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "prod")

s3: "S3Client" = boto3.client("s3")
logger = Logger(service="difference-in-docs")


class InfraError(Exception):
    """Raised for failures that should fail the Lambda, which will trigger an automated SQS retry / DLQ)."""


@event_source(data_class=SQSEvent)
def lambda_handler(event: SQSEvent, _context: LambdaContext) -> dict:
    """Difference in Docs Lambda Handler."""
    raw_records = event.get("Records")
    if not isinstance(raw_records, list) or not raw_records:
        raise InfraError("SQS event has no Records")

    for record in event.records:
        s3_event = S3EventBridgeNotificationEvent(record.json_body)

        bucket_name = s3_event.detail.bucket.name
        manifest_key = unquote_plus(s3_event.detail.object.key)

        persistence_id = persistence_id_from_key(manifest_key)
        did_input_manifest = get_input_manifest(bucket_name, manifest_key)

        did_complete_output_records: list[DIDOutputFile] = []

        for entry in did_input_manifest.files:
            set_id = entry.setId
            version_number = entry.versionNumber

            eicr_out_key = get_did_output_key(entry.eicr)
            rr_out_key = get_did_output_key(entry.rr)

            # write eICR to DIDOutput/
            put_object(bucket_name, eicr_out_key, get_object(bucket_name, entry.eicr))

            # write RR to DIDOutput/
            put_object(bucket_name, rr_out_key, get_object(bucket_name, entry.rr))

            did_complete_output_records.append(
                DIDOutputFile(
                    setId=set_id,
                    versionNumber=version_number,
                    eicr=eicr_out_key,
                    rr=rr_out_key,
                    eicr_diff_output=None,  # TODO: add this once we're actually diffing
                    is_actionable=True,  # TODO: add this once we're actually diffing
                )
            )

        # write to DIDComplete/
        did_complete_manifest = DIDCompleteManifest(Files=did_complete_output_records)
        did_complete_key = f"{DID_COMPLETE_PREFIX}{persistence_id}"
        put_object(
            bucket_name,
            did_complete_key,
            did_complete_manifest.model_dump_json(by_alias=True, indent=2).encode(
                "utf-8"
            ),
        )

    return {"statusCode": 200, "message": "OK"}


def get_input_manifest(bucket: str, key: str) -> DIDInputManifest:
    """Reads and validates manifest file from S3."""
    try:
        return DIDInputManifest.model_validate_json(get_object(bucket, key))
    except ValidationError as exc:
        raise InfraError(f"Invalid manifest s3://{bucket}/{key}") from exc


def get_object(bucket: str, key: str) -> bytes:
    """Utility to get object from S3."""
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except Exception as exc:
        raise InfraError(f"S3 get_object failed s3://{bucket}/{key}: {exc}") from exc


def put_object(bucket: str, key: str, data: bytes) -> None:
    """Utility to put object to S3."""
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=data)
    except Exception as exc:
        raise InfraError(f"S3 put_object failed s3://{bucket}/{key}: {exc}") from exc


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


def get_did_output_key(source_key: str) -> str:
    """Converts an S3 Key into a DIDOutput prefixed key."""
    output_prefix = get_did_output_prefix(source_key)
    return f"{output_prefix}/{get_key_basename(source_key)}"


def get_did_output_prefix(source_key: str) -> str:
    """Extracts S3 Key prefix from DIDInput S3 key."""
    parts = source_key.strip("/").split("/")
    if len(parts) <= 2:
        raise InfraError(f"S3 key has nothing after prefix: {source_key}")
    return f"{DID_OUTPUT_PREFIX}{'/'.join(parts[1:-1])}"


def get_key_basename(source_key: str) -> str:
    """Gets basename of an S3 key."""
    key = source_key.strip("/")
    if not key:
        raise InfraError(f"Invalid S3 key: {source_key}")
    return key.rsplit("/", 1)[-1]
