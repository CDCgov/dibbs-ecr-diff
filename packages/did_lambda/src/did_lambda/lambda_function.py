"""Ingest manifests delivered through S3 and SQS."""

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote_plus

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.data_classes import (
    SQSEvent,
    event_source,
)
from aws_lambda_powertools.utilities.typing import LambdaContext

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
    bucket, input_key = parse_sqs_s3_event(event)
    persistence_id = persistence_id_from_key(input_key)

    batch = read_json(bucket, input_key)
    files = batch.get("Files")

    if not isinstance(files, list):
        raise InfraError(f"Batch file missing Files list: s3://{bucket}/{input_key}")

    did_complete_files: list[dict[str, Any]] = []

    for entry in files:
        eicr_key = entry["eicr"]
        # rr_key = entry["rr"]
        set_id = entry.get("setId")
        version_number = entry.get("versionNumber")

        # Ensure listed refined docs are readable (real DiD would load + compare).
        _ = read_bytes(bucket, eicr_key)
        # _ = read_bytes(bucket, rr_key)

        out_eicr = to_did_output_key(eicr_key)
        # out_rr = to_did_output_key(rr_key)

        # Stub: empty placeholders for per-doc DiD results.
        # this is where the diff output would go
        # write_bytes(bucket, out_eicr, b"")
        # write_bytes(bucket, out_rr, b"")

        print(out_eicr)

        did_complete_files.append(
            {
                "eicr": out_eicr,
                # "rr": out_rr,
                "setId": set_id,
                "versionNumber": version_number,
            }
        )

    complete_key = f"{DID_COMPLETE_PREFIX}{persistence_id}"
    complete_body = {"Files": did_complete_files}
    write_json(bucket, complete_key, complete_body)

    return {
        "bucket": bucket,
        "input_key": input_key,
        "persistence_id": persistence_id,
        "did_complete_key": complete_key,
        "processed_count": len(did_complete_files),
    }

    # bucket_name = event.detail.bucket.name
    # file_key = event.detail.object.key

    # print(bucket_name)
    # print(file_key)
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
    # return {"statusCode": 200, "message": "OK"}


def _get_manifest(bucket: str, key: str) -> Manifest:
    response = s3.get_object(Bucket=bucket, Key=key)
    with response["Body"] as body:
        return Manifest.model_validate_json(body.read())


def parse_sqs_s3_event(event: SQSEvent) -> tuple[str, str]:
    """Parse SQS S3 Event and return bucket name and S3 Object Key."""
    records = event.get("Records") or []
    if not records:
        raise InfraError("SQS event has no Records")

    body_raw = records[0].get("body")
    if not body_raw:
        raise InfraError("SQS record missing body")

    try:
        body = json.loads(body_raw) if isinstance(body_raw, str) else body_raw
    except json.JSONDecodeError as exc:
        raise InfraError("SQS body is not valid JSON") from exc

    detail = body.get("detail") or {}
    bucket = (detail.get("bucket") or {}).get("name")
    key = (detail.get("object") or {}).get("key")
    if not bucket or not key:
        raise InfraError("S3 Object Created detail missing bucket/object.key")

    return bucket, unquote_plus(key)


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


def read_bytes(bucket: str, key: str) -> bytes:
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except Exception as exc:  # noqa: BLE001 — surface as infra for retry/DLQ
        raise InfraError(f"S3 get_object failed s3://{bucket}/{key}: {exc}") from exc


def read_json(bucket: str, key: str) -> dict[str, Any]:
    return json.loads(read_bytes(bucket, key).decode("utf-8"))


def to_did_output_key(source_key: str) -> str:
    """Replace the first S3 key segment with DIDOutput/."""
    parts = source_key.strip("/").split("/", 1)
    if len(parts) != 2 or not parts[1]:
        raise InfraError(f"S3 key has nothing after prefix: {source_key}")
    return f"{DID_OUTPUT_PREFIX}{parts[1]}"


def write_bytes(bucket: str, key: str, data: bytes) -> None:
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=data)
    except Exception as exc:  # noqa: BLE001
        raise InfraError(f"S3 put_object failed s3://{bucket}/{key}: {exc}") from exc


def write_json(bucket: str, key: str, payload: dict[str, Any]) -> None:
    write_bytes(bucket, key, json.dumps(payload, indent=2).encode("utf-8"))
