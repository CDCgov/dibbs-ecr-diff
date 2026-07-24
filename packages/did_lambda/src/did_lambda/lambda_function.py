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

from .models import DIDOutputRecord, Manifest

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
        logger.info(manifest)

        did_complete_files: list[DIDOutputRecord] = []

        for entry in manifest.files:
            set_id = entry.setId
            version_number = entry.versionNumber

            # query for latest record
            results = eicr_records.query(
                KeyConditionExpression=(
                    Key("setId").eq(set_id) & Key("versionNumber").lt(version_number)
                ),
                FilterExpression=Attr("isActionable").eq(True),
                ScanIndexForward=False,  # force descending order
                Limit=1,
            )

            latest = results["Items"][0] if results["Items"] else None

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
            else:
                # fetch the latest S3 document
                before_s3_key = latest.get("s3Key", None)
                before_version = latest.get("versionNumber", None)

                if before_s3_key is None or before_version is None:
                    raise InfraError(f"Invalid latest record for setId: {set_id}")

                before_xml = read_object(bucket, str(before_s3_key))
                after_xml = read_object(bucket, entry.eicr)

                diff_output = diff_xml(
                    DiffingOptions(file1=before_xml, file2=after_xml), BASELINE_CONFIG
                )

                is_actionable = len(diff_output.changes) > 0
                s3_key_diff_output = to_did_output_key(entry.eicr)

                # write this new eicr
                eicr_records.put_item(
                    Item={
                        "setId": set_id,
                        "versionNumber": version_number,
                        "s3Key": entry.eicr,
                        "s3KeyRR": entry.rr,
                        "s3KeyDiffOutput": s3_key_diff_output,
                        "processedAt": get_timestamp(),
                        "isActionable": is_actionable,
                        "comparedToVersion": before_version,
                    }
                )

                # write the diff output to S3
                write_object(
                    bucket,
                    s3_key_diff_output,
                    diff_output.model_dump_json(indent=2).encode("utf-8"),
                )

                did_complete_files.append(
                    DIDOutputRecord(
                        setId=set_id,
                        versionNumber=version_number,
                        eicr=to_did_output_key(entry.eicr),
                        rr=to_did_output_key(entry.rr) if entry.rr else None,
                        eicr_diff_output=s3_key_diff_output,
                        rr_diff_output=None,
                    )
                )

        did_complete_key = f"{DID_COMPLETE_PREFIX}{persistence_id}"
        did_complete_body = {"Files": did_complete_files}
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


def to_did_output_key(source_key: str) -> str:
    """Replace the first S3 key segment with DIDOutput/."""
    parts = source_key.strip("/").split("/", 1)
    if len(parts) != 2 or not parts[1]:
        raise InfraError(f"S3 key has nothing after prefix: {source_key}")
    return f"{DID_OUTPUT_PREFIX}{parts[1]}"


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
