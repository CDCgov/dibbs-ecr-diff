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
from core import Configuration, DiffingOptions, DiffOutput, diff_xml
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

        bucket_name = s3_event.detail.bucket.name
        manifest_key = unquote_plus(s3_event.detail.object.key)

        persistence_id = persistence_id_from_key(manifest_key)
        manifest = get_manifest(bucket_name, manifest_key)

        did_complete_files: list[DIDOutputRecord] = []

        for entry in manifest.files:
            set_id = entry.setId
            version_number = entry.versionNumber

            eicr_out_key = get_did_output_key(entry.eicr)
            rr_out_key = get_did_output_key(entry.rr) if entry.rr else None

            augmented_eicr: bytes | None = None
            diff_output_key: str | None = None

            latest = get_latest_actionable_record(set_id, version_number)

            if latest is None:
                # write eICR metadata to DB as the new baseline for this setId
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
                output_prefix = get_did_output_prefix(entry.eicr)
                diff_output_key = f"{output_prefix}/{set_id}_eicr_diff"

                before_xml = read_object(bucket_name, latest.s3Key)
                after_xml = read_object(bucket_name, entry.eicr)

                logger.info(
                    f"Diffing version {version_number} against version {latest.versionNumber} of {set_id}"
                )

                diff_output = diff_xml(
                    DiffingOptions(file1=before_xml, file2=after_xml), BASELINE_CONFIG
                )

                augmented_eicr = get_augmented_eicr(diff_output, after_xml)

                # write the diff output to S3
                write_object(
                    bucket_name,
                    diff_output_key,
                    diff_output.model_dump_json(indent=2).encode("utf-8"),
                )

                # write eICR metadata to DB
                eicr_records.put_item(
                    Item={
                        "setId": set_id,
                        "versionNumber": version_number,
                        "s3Key": entry.eicr,
                        "s3KeyRR": entry.rr,
                        "s3KeyDiffOutput": diff_output_key,
                        "processedAt": get_timestamp(),
                        "isActionable": len(diff_output.changes) > 0,
                        "comparedToVersion": latest.versionNumber,
                    }
                )

            write_object(
                bucket_name,
                eicr_out_key,
                augmented_eicr
                if augmented_eicr
                else read_object(bucket_name, entry.eicr),
            )

            if entry.rr and rr_out_key:
                write_object(
                    bucket_name, rr_out_key, read_object(bucket_name, entry.rr)
                )

            did_complete_files.append(
                DIDOutputRecord(
                    setId=set_id,
                    versionNumber=version_number,
                    eicr=eicr_out_key,
                    rr=rr_out_key,
                    eicr_diff_output=diff_output_key,
                )
            )

        # TODO: should this be an empty array when there are no actionable changes?
        did_complete_key = f"{DID_COMPLETE_PREFIX}{persistence_id}"
        did_complete_body = {
            "Files": [record.model_dump() for record in did_complete_files]
        }
        write_object(
            bucket_name,
            did_complete_key,
            json.dumps(did_complete_body, indent=2).encode("utf-8"),
        )

    return {"statusCode": 200, "message": "OK"}


def get_augmented_eicr(_diff_output: DiffOutput, eicr: bytes) -> bytes:
    """TODO: stub for augmenting the eicr."""
    return eicr


def get_latest_actionable_record(
    set_id: str, version_number: int
) -> EICRStorageRecord | None:
    """Retrieves the latest earlier actionable record for a given setId and versionNumber."""
    results = eicr_records.query(
        KeyConditionExpression=(
            Key("setId").eq(set_id) & Key("versionNumber").lt(version_number)
        ),
        FilterExpression=Attr("isActionable").eq(True),
        ScanIndexForward=False,  # force descending order
    )

    return (
        EICRStorageRecord.model_validate(results["Items"][0])
        if results["Items"]
        else None
    )


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
    """Utility to read object from S3."""
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except Exception as exc:
        raise InfraError(f"S3 get_object failed s3://{bucket}/{key}: {exc}") from exc


def write_object(bucket: str, key: str, data: bytes) -> None:
    """Utility to write object to S3."""
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=data)
    except Exception as exc:
        raise InfraError(f"S3 put_object failed s3://{bucket}/{key}: {exc}") from exc


def get_did_output_key(source_key: str) -> str:
    """Converts an S3 Key into a DIDOutput prefixed key."""
    output_prefix = get_did_output_prefix(source_key)
    return f"{output_prefix}/{get_last_key_part(source_key)}"


def get_did_output_prefix(source_key: str) -> str:
    """Extracts S3 Key prefix from DIDInput S3 key."""
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
