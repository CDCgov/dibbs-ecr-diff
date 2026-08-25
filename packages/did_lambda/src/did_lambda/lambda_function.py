"""Ingest manifests delivered through S3 and SQS."""

import os
from collections import Counter
from urllib.parse import unquote_plus

from aws_lambda_powertools.utilities.data_classes import (
    S3EventBridgeNotificationEvent,
    SQSEvent,
    SQSRecord,
    event_source,
)
from aws_lambda_powertools.utilities.typing import LambdaContext
from core import ChangeType, DiffOutput, diff_xml
from core.augment import (
    AugmentationRun,
    augment_eicr_in_place,
    augment_rr_in_place,
    create_augmentation_run,
)
from core.configurations import load_configuration
from core.datetime_utils import get_current_datetime
from lxml import etree
from lxml.etree import ElementTree
from pydantic import ValidationError

from .dynamodb import get_before_actionable_record, put_eicr_record
from .models import (
    DIDCompleteManifest,
    DIDInputFile,
    DIDInputManifest,
    DIDOutputFile,
    EICRStorageRecord,
)
from .s3 import get_object, get_object_xml_tree, put_object
from .telemetry import (
    BatchProcessingStats,
    DocumentTelemetry,
    ManifestEntryResult,
    log_doc_and_changes,
    log_documents_processed_by_condition,
    metrics,
    raise_processing_failure,
    record_processing_metrics,
)
from .telemetry_helpers import (
    ConditionCode,
    condition_codes_from_rr,
    encounter_type_from_eicr,
    make_persistence_id_with_index,
)
from .utils import (
    InfraError,
    get_did_output_key,
    get_did_output_path,
    persistence_id_from_manifest_key,
)

OUTPUT_PREFIX = os.environ.get("OUTPUT_PREFIX", "DIDOutputV2/")
COMPLETE_PREFIX = os.environ.get("COMPLETE_PREFIX", "DIDCompleteV2/")

config = load_configuration("aphl_baseline.json")


@metrics.log_metrics
@event_source(data_class=SQSEvent)
def lambda_handler(event: SQSEvent, _context: LambdaContext) -> dict:
    """Difference in Docs Lambda Handler."""
    stats = BatchProcessingStats()
    try:
        raw_records = event.get("Records")
        if not isinstance(raw_records, list) or not raw_records:
            raise_processing_failure(
                "manifest_load", InfraError("SQS event has no Records")
            )
        if len(raw_records) != 1:
            stats.manifests_failed += len(raw_records)
            raise_processing_failure(
                "manifest_load",
                InfraError("SQS event must contain exactly one manifest"),
            )

        record = next(event.records)
        try:
            process_sqs_record(record, stats)
        except Exception:
            stats.manifests_failed += 1
            raise
        else:
            stats.manifests_processed += 1

        return {"statusCode": 200, "message": "OK"}
    finally:
        record_processing_metrics(stats)
        log_documents_processed_by_condition(stats)


def process_sqs_record(record: SQSRecord, stats: BatchProcessingStats) -> None:
    """Process an SQS record containing an S3 event."""
    try:
        s3_event = S3EventBridgeNotificationEvent(record.json_body)
        bucket_name = s3_event.detail.bucket.name
        did_input_manifest_key = unquote_plus(s3_event.detail.object.key)
        persistence_id = persistence_id_from_manifest_key(did_input_manifest_key)
        did_input_manifest = get_input_manifest(bucket_name, did_input_manifest_key)
    except Exception as exc:
        raise_processing_failure("manifest_load", exc)

    did_complete_output_files: list[DIDOutputFile] = []
    pending_results: list[ManifestEntryResult] = []
    pending_condition_counts: Counter[ConditionCode] = Counter()

    for index, entry in enumerate(did_input_manifest.files):
        try:
            result = process_manifest_entry(
                bucket_name,
                persistence_id,
                entry,
                index,
                pending_condition_counts,
            )
        except Exception:
            stats.documents_failed += 1
            raise

        pending_results.append(result)
        did_complete_output_files.append(result.output_file)

    try:
        did_complete_manifest = DIDCompleteManifest(Files=did_complete_output_files)
        did_complete_manifest_key = f"{COMPLETE_PREFIX}{persistence_id}"
        put_object(
            bucket_name,
            did_complete_manifest_key,
            did_complete_manifest.model_dump_json(by_alias=True, indent=2).encode(
                "utf-8"
            ),
        )
    except Exception as exc:
        raise_processing_failure("completion_write", exc)

    # Commit success telemetry only for a fully completed manifest. If entry
    # processing or the completion write fails, these local buffers are discarded.
    for result in pending_results:
        stats.record_document_processed(result)
        log_doc_and_changes(result)
    stats.documents_processed_by_condition.update(pending_condition_counts)


def process_manifest_entry(
    bucket_name: str,
    persistence_id: str,
    entry: DIDInputFile,
    index: int,
    documents_processed_by_condition: Counter[ConditionCode] | None = None,
) -> ManifestEntryResult:
    """Process a single DID input manifest entry."""
    stage = "document_load"
    persistence_id_with_index = make_persistence_id_with_index(persistence_id, index)

    try:
        is_remainder_rr = "unrefined_rr" in entry.rr.lower()
        set_id = entry.setId
        version_number = entry.versionNumber

        jurisdiction_id = ",".join(entry.jurisdictions)
        before_record = get_before_actionable_record(set_id, version_number)
        compared_to_version = before_record.versionNumber if before_record else None
        is_actionable = before_record is None

        diff_output: DiffOutput | None = None
        diff_output_key: str | None = None

        eicr_tree = get_object_xml_tree(bucket_name, entry.eicr)
        rr_tree = get_object_xml_tree(bucket_name, entry.rr)
        encounter_type = encounter_type_from_eicr(eicr_tree)
        condition_codes = condition_codes_from_rr(rr_tree)

        eicr_out_key: str | None = None
        rr_out_key = get_did_output_key(
            root_prefix=OUTPUT_PREFIX,
            persistence_id=persistence_id,
            source_key=entry.rr,
            fallback_basename="RR.xml",
        )

        if is_remainder_rr:
            stage = "output_write"
            put_object(bucket_name, rr_out_key, get_object(bucket_name, entry.rr))
        else:
            if before_record:
                before_tree = get_object_xml_tree(bucket_name, before_record.s3Key)

                stage = "diff"
                diff_output = diff_xml(before_tree, eicr_tree, config)
                is_actionable = diff_output.hasActionableChanges

                output_path = get_did_output_path(
                    OUTPUT_PREFIX, persistence_id, entry.eicr
                )
                diff_output_key = f"{output_path}/diff_v{compared_to_version}_to_v{version_number}_{index}.json"

                stage = "output_write"
                put_object(
                    bucket_name,
                    diff_output_key,
                    diff_output.model_dump_json(indent=2).encode("utf-8"),
                )

            stage = "augmentation"
            eicr_root = eicr_tree.getroot()
            augmentation_run = create_augmentation_run(eicr_root)
            augmented_eicr = get_augmented_eicr(
                eicr_root, augmentation_run, jurisdiction_id, diff_output
            )
            augmented_rr = get_augmented_rr(rr_tree, augmentation_run, jurisdiction_id)

            stage = "output_write"
            eicr_out_key = get_did_output_key(
                root_prefix=OUTPUT_PREFIX,
                persistence_id=persistence_id,
                source_key=entry.eicr,
                fallback_basename="eICR.xml",
            )
            put_object(bucket_name, eicr_out_key, augmented_eicr)
            put_object(bucket_name, rr_out_key, augmented_rr)

            put_eicr_record(
                EICRStorageRecord(
                    setId=set_id,
                    versionNumber=version_number,
                    s3Key=entry.eicr,
                    s3KeyRR=entry.rr,
                    s3KeyDiffOutput=diff_output_key,
                    processedAt=get_current_datetime(),
                    isActionable=is_actionable,
                    comparedToVersion=compared_to_version,
                )
            )

        changes = tuple(diff_output.changes) if diff_output is not None else ()
        change_counts = Counter(change.changeType for change in changes)

        result = ManifestEntryResult(
            output_file=DIDOutputFile(
                setId=set_id,
                versionNumber=version_number,
                eicr=eicr_out_key,
                rr=rr_out_key,
                eicr_diff_output=diff_output_key,
                is_actionable=is_actionable,
                jurisdictions=entry.jurisdictions,
            ),
            changes=changes,
            telemetry=DocumentTelemetry(
                persistence_id_with_index=persistence_id_with_index,
                version_number=version_number,
                encounter_type=encounter_type,
                unique_condition_count=len(condition_codes),
                changes_added=change_counts[ChangeType.ADDED],
                changes_updated=change_counts[ChangeType.UPDATED],
                changes_deleted=change_counts[ChangeType.DELETED],
            ),
        )
        if documents_processed_by_condition is not None:
            documents_processed_by_condition.update(condition_codes)
        return result
    except Exception as exc:
        raise_processing_failure(stage, exc, persistence_id_with_index)


def get_augmented_eicr(
    eicr_root: etree._Element,
    augmentation_run: AugmentationRun,
    jurisdiction_id: str,
    diff_output: DiffOutput | None,
) -> bytes:
    """Return augmented eICR."""
    augment_eicr_in_place(
        eicr_root=eicr_root,
        run=augmentation_run,
        jurisdiction_id=jurisdiction_id,
        diff_output=diff_output,
    )

    return etree.tostring(
        eicr_root, pretty_print=True, xml_declaration=True, encoding="utf-8"
    )


def get_augmented_rr(
    rr_tree: ElementTree, augmentation_run: AugmentationRun, jurisdiction_id: str
) -> bytes:
    """Return augmented RR."""
    rr_root = rr_tree.getroot()
    augment_rr_in_place(
        rr_root=rr_root, run=augmentation_run, jurisdiction_id=jurisdiction_id
    )

    return etree.tostring(
        rr_root, pretty_print=True, xml_declaration=True, encoding="utf-8"
    )


def get_input_manifest(bucket: str, key: str) -> DIDInputManifest:
    """Read and validate a manifest file from S3."""
    try:
        return DIDInputManifest.model_validate_json(get_object(bucket, key))
    except ValidationError as exc:
        raise InfraError(f"Invalid manifest s3://{bucket}/{key}") from exc
