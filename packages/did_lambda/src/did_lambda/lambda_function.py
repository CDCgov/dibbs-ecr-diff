"""Ingest manifests delivered through S3 and SQS."""

import os
from typing import TYPE_CHECKING
from urllib.parse import unquote_plus

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.data_classes import (
    S3EventBridgeNotificationEvent,
    SQSEvent,
    SQSRecord,
    event_source,
)
from aws_lambda_powertools.utilities.typing import LambdaContext
from boto3.dynamodb.conditions import Attr, Key
from core import DiffOutput, diff_xml
from core.augment import (
    augment_eicr_in_place,
    augment_rr_in_place,
    create_augmentation_run,
)
from core.configurations import load_configuration
from lxml import etree
from lxml.etree import ElementTree
from pydantic import ValidationError

from .models import (
    DIDCompleteManifest,
    DIDInputFile,
    DIDInputManifest,
    DIDOutputFile,
    EICRStorageRecord,
)
from .utils import (
    InfraError,
    get_did_output_key,
    get_did_output_prefix,
    get_timestamp,
    jurisdiction_id_from_key,
    parse_xml,
    persistence_id_from_key,
)

if TYPE_CHECKING:
    from types_boto3_dynamodb import DynamoDBServiceResource
    from types_boto3_s3 import S3Client

DID_OUTPUT_PREFIX = os.environ.get("DID_OUTPUT_PREFIX", "DIDOutput/")
DID_COMPLETE_PREFIX = os.environ.get("DID_COMPLETE_PREFIX", "DIDComplete/")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "did-eicr-record")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "prod")
CONFIGURATION_FILE = os.environ.get("CONFIGURATION_FILE", "aphl_baseline.json")

s3: "S3Client" = boto3.client("s3")
dynamodb: "DynamoDBServiceResource" = boto3.resource("dynamodb")

db = dynamodb.Table(DYNAMODB_TABLE)
logger = Logger("difference-in-docs")
config = load_configuration(CONFIGURATION_FILE)


@event_source(data_class=SQSEvent)
def lambda_handler(event: SQSEvent, _context: LambdaContext) -> dict:
    """Difference in Docs Lambda Handler."""
    raw_records = event.get("Records")
    if not isinstance(raw_records, list) or not raw_records:
        raise InfraError("SQS event has no Records")

    for record in event.records:
        process_sqs_record(record)

    return {"statusCode": 200, "message": "OK"}


def process_sqs_record(record: SQSRecord) -> None:
    """Process an SQS record containing an S3 event."""
    s3_event = S3EventBridgeNotificationEvent(record.json_body)

    bucket_name = s3_event.detail.bucket.name
    did_input_manifest_key = unquote_plus(s3_event.detail.object.key)

    persistence_id = persistence_id_from_key(did_input_manifest_key)
    did_input_manifest = get_input_manifest(bucket_name, did_input_manifest_key)
    did_complete_output_files: list[DIDOutputFile] = []

    # process every DIDInputFile in the batch
    for entry in did_input_manifest.files:
        did_complete_output_files.append(
            process_manifest_entry(bucket_name, persistence_id, entry)
        )

    # write to DIDComplete/
    did_complete_manifest = DIDCompleteManifest(Files=did_complete_output_files)
    did_complete_manifest_key = f"{DID_COMPLETE_PREFIX}{persistence_id}"
    put_object(
        bucket_name,
        did_complete_manifest_key,
        did_complete_manifest.model_dump_json(by_alias=True, indent=2).encode("utf-8"),
    )


def process_manifest_entry(
    bucket_name: str, persistence_id: str, entry: DIDInputFile
) -> DIDOutputFile:
    """Process a single DID input manifest entry."""
    set_id = entry.setId
    version_number = entry.versionNumber

    eicr_out_key = get_did_output_key(DID_OUTPUT_PREFIX, entry.eicr)
    rr_out_key = get_did_output_key(DID_OUTPUT_PREFIX, entry.rr)
    jurisdiction_id = jurisdiction_id_from_key(persistence_id, entry.eicr)

    eicr_tree = parse_xml(get_object(bucket_name, entry.eicr))
    rr_tree = parse_xml(get_object(bucket_name, entry.rr))

    before_record = get_before_actionable_record(set_id, version_number)
    compared_to_version = before_record.versionNumber if before_record else None
    is_actionable = before_record is None
    diff_output: DiffOutput | None = None
    diff_output_key: str | None = None

    if before_record:
        output_prefix = get_did_output_prefix(DID_OUTPUT_PREFIX, entry.eicr)
        diff_output_key = f"{output_prefix}/{set_id}_eicr_diff"
        before_tree = parse_xml(get_object(bucket_name, before_record.s3Key))

        logger.info(
            f"Diffing version {version_number} against version {before_record.versionNumber} of {set_id}"
        )

        diff_output = diff_xml(before_tree, eicr_tree, config)
        is_actionable = diff_output.hasActionableChanges

    augmented_eicr = get_augmented_eicr(eicr_tree, jurisdiction_id, diff_output)
    augmented_rr = get_augmented_rr(rr_tree, jurisdiction_id)

    if diff_output_key is not None and diff_output is not None:
        put_object(
            bucket_name,
            diff_output_key,
            diff_output.model_dump_json(indent=2).encode("utf-8"),
        )

    # write eICR metadata to DB
    db.put_item(
        Item={
            "setId": set_id,
            "versionNumber": version_number,
            "s3Key": entry.eicr,
            "s3KeyRR": entry.rr,
            "s3KeyDiffOutput": diff_output_key,
            "processedAt": get_timestamp(),
            "isActionable": is_actionable,
            "comparedToVersion": compared_to_version,
        }
    )

    # write augmented eicr to DIDOutput/
    put_object(bucket_name, eicr_out_key, augmented_eicr)

    # write augmented rr to DIDOutput/
    put_object(bucket_name, rr_out_key, augmented_rr)

    return DIDOutputFile(
        setId=set_id,
        versionNumber=version_number,
        eicr=eicr_out_key,
        rr=rr_out_key,
        eicr_diff_output=diff_output_key,
        is_actionable=is_actionable,
    )


def get_augmented_eicr(
    eicr_tree: ElementTree, jurisdiction_id: str, diff_output: DiffOutput | None
) -> bytes:
    """Return augmented eICR."""
    eicr_root = eicr_tree.getroot()
    augmentation_run = create_augmentation_run(eicr_root)

    augment_eicr_in_place(
        eicr_root=eicr_root,
        run=augmentation_run,
        jurisdiction_id=jurisdiction_id,
        diff_output=diff_output,
    )

    return etree.tostring(
        eicr_root, pretty_print=True, xml_declaration=True, encoding="utf-8"
    )


def get_augmented_rr(rr_tree: ElementTree, jurisdiction_id: str) -> bytes:
    """Return augmented RR."""
    rr_root = rr_tree.getroot()
    augmentation_run = create_augmentation_run(rr_root)

    augment_rr_in_place(
        rr_root=rr_root, run=augmentation_run, jurisdiction_id=jurisdiction_id
    )

    return etree.tostring(
        rr_root, pretty_print=True, xml_declaration=True, encoding="utf-8"
    )


def get_before_actionable_record(
    set_id: str, version_number: int
) -> EICRStorageRecord | None:
    """Retrieves the latest earlier actionable record for a given setId and versionNumber."""
    items = db.query(
        KeyConditionExpression=(
            Key("setId").eq(set_id) & Key("versionNumber").lt(version_number)
        ),
        FilterExpression=Attr("isActionable").eq(True),
        ScanIndexForward=False,  # force descending order
    )["Items"]

    return EICRStorageRecord.model_validate(items[0]) if items else None


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
