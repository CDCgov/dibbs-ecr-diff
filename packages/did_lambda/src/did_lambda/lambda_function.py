"""Ingest manifests delivered through S3 and SQS."""

import json
from datetime import UTC, datetime
from pathlib import Path
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
from boto3.dynamodb.conditions import Attr, Key
from core import Configuration, DiffingOptions, diff_xml
from pydantic import ValidationError

from .models import DIDOutputRecord, EICRStorageRecord, Manifest

if TYPE_CHECKING:
    from types_boto3_dynamodb import DynamoDBServiceResource
    from types_boto3_s3 import S3Client

DID_OUTPUT_PREFIX = "DIDOutput/"
DID_COMPLETE_PREFIX = "DIDComplete/"
DYNAMODB_TABLE_NAME = "did-eicr-record"

s3: "S3Client" = boto3.client("s3")
dynamodb: "DynamoDBServiceResource" = boto3.resource("dynamodb")

eicr_records = dynamodb.Table(DYNAMODB_TABLE_NAME)
logger = Logger("did-lambda")

config_path = Path(__file__).parent / "aphl_baseline_config.json"
with config_path.open(encoding="utf-8") as config_file:
    BASELINE_CONFIG = Configuration(**json.load(config_file))


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

        bucket = s3_event.detail.bucket.name
        input_key = unquote_plus(s3_event.detail.object.key)
        persistence_id = persistence_id_from_key(input_key)

        manifest = get_manifest(bucket, input_key)

        did_complete_files: list[DIDOutputRecord] = []

        for entry in manifest.files:
            set_id = entry.setId
            version_number = entry.versionNumber

            output_prefix = get_did_output_prefix(entry.eicr)
            eicr_out_key = f"{output_prefix}/{get_last_key_part(entry.eicr)}"
            rr_out_key = (
                f"{output_prefix}/{get_last_key_part(entry.rr)}" if entry.rr else None
            )

            # query for latest record
            results = eicr_records.query(
                KeyConditionExpression=(
                    Key("setId").eq(set_id) & Key("versionNumber").lt(version_number)
                ),
                FilterExpression=Attr("isActionable").eq(True),
                ScanIndexForward=False,  # force descending order
                Limit=1,
            )

            latest = (
                EICRStorageRecord.model_validate(results["Items"][0])
                if results["Items"]
                else None
            )

            if latest is None:
                # this eicr is the baseline
                eicr_records.put_item(
                    Item={
                        "setId": set_id,
                        "versionNumber": version_number,
                        "s3Key": entry.eicr,
                        "s3KeyRR": entry.rr,
                        "processedAt": get_timestamp(),
                        "isActionable": True,
                    }
                )

                # write the unchanged eicr && rr to DIDOutput
                write_object(bucket, eicr_out_key, read_object(bucket, entry.eicr))
                if entry.rr and rr_out_key:
                    write_object(bucket, rr_out_key, read_object(bucket, entry.rr))

                did_complete_files.append(
                    DIDOutputRecord(
                        setId=set_id,
                        versionNumber=version_number,
                        eicr=eicr_out_key,
                        rr=rr_out_key,
                        eicr_diff_output=None,
                        rr_diff_output=None,
                    )
                )
            else:
                before_s3_key = latest.s3Key
                before_version = latest.versionNumber

                eicr_diff_out_key = f"{output_prefix}/{set_id}_eicr_diff"
                _rr_diff_out_key = f"{output_prefix}/{set_id}_rr_diff"  # unused

                before_xml = read_object(bucket, before_s3_key)
                after_xml = read_object(bucket, entry.eicr)

                logger.info(
                    f"Diffing version {version_number} against version {before_version} of {set_id}"
                )

                diff_output = diff_xml(
                    DiffingOptions(file1=before_xml, file2=after_xml), BASELINE_CONFIG
                )

                is_actionable = len(diff_output.changes) > 0

                # write this new eicr
                eicr_records.put_item(
                    Item={
                        "setId": set_id,
                        "versionNumber": version_number,
                        "s3Key": entry.eicr,
                        "s3KeyRR": entry.rr,
                        "s3KeyDiffOutput": eicr_diff_out_key,
                        "processedAt": get_timestamp(),
                        "isActionable": is_actionable,
                        "comparedToVersion": before_version,
                    }
                )

                # write the diff output to S3
                write_object(
                    bucket,
                    eicr_diff_out_key,
                    diff_output.model_dump_json(indent=2).encode("utf-8"),
                )

                # TODO: write augmented eICR/RR
                # write the unchanged eicr && rr to DIDOutput for now
                write_object(bucket, eicr_out_key, read_object(bucket, entry.eicr))
                if entry.rr and rr_out_key:
                    write_object(bucket, rr_out_key, read_object(bucket, entry.rr))

                did_complete_files.append(
                    DIDOutputRecord(
                        setId=set_id,
                        versionNumber=version_number,
                        eicr=eicr_out_key,
                        rr=rr_out_key,
                        eicr_diff_output=eicr_diff_out_key,
                        rr_diff_output=None,
                    )
                )

        # TODO: should this be an empty array when there are no actionable changes?
        did_complete_key = f"{DID_COMPLETE_PREFIX}{persistence_id}"
        did_complete_body = {
            "Files": [record.model_dump() for record in did_complete_files]
        }
        write_object(
            bucket,
            did_complete_key,
            json.dumps(did_complete_body, indent=2).encode("utf-8"),
        )

    return {"statusCode": 200, "message": "OK"}


def get_timestamp() -> str:
    """Generate a new ISO-8601 timestamp."""
    return datetime.now(UTC).isoformat()


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


def write_object(bucket: str, key: str, data: bytes) -> None:
    """Generic utility to write object to S3."""
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=data)
    except Exception as exc:
        raise InfraError(f"S3 put_object failed s3://{bucket}/{key}: {exc}") from exc


def get_did_output_prefix(source_key: str) -> str:
    """Converts a DIDInput S3 key into a DIDOutput S3 key."""
    parts = source_key.strip("/").split("/")
    if len(parts) <= 2:
        raise InfraError(f"S3 key has nothing after prefix: {source_key}")
    return f"{DID_OUTPUT_PREFIX}{'/'.join(parts[1:-1])}"


def get_last_key_part(source_key: str) -> str:
    """Gets last part of an S3 key."""
    key = source_key.strip("/")
    if not key:
        raise InfraError(f"Invalid S3 key: {source_key}")
    return key.rsplit("/", 1)[-1]


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
