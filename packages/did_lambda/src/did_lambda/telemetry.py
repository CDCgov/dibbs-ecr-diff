"""Aggregate and emit operational telemetry for the Difference in Docs Lambda."""

import os
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Never

from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit, single_metric
from core import Change

from .models import DIDOutputFile
from .telemetry_helpers import ConditionCode, change_path_for_logging
from .utils import InfraError

ENVIRONMENT = os.environ.get("ENV", "production")
METRICS_NAMESPACE = os.environ.get("POWERTOOLS_METRICS_NAMESPACE", "eICRDiff")
SERVICE_NAME = os.environ.get("POWERTOOLS_SERVICE_NAME", "difference-in-docs")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG")

logger = Logger(service=SERVICE_NAME, level=LOG_LEVEL)
metrics = Metrics(namespace=METRICS_NAMESPACE, service=SERVICE_NAME)


@dataclass(frozen=True, slots=True)
class DocumentTelemetry:
    """Document metadata available to telemetry consumers."""

    persistence_id_with_index: str
    version_number: int
    encounter_type: str
    unique_condition_count: int = 0
    changes_added: int = field(kw_only=True)
    changes_updated: int = field(kw_only=True)
    changes_deleted: int = field(kw_only=True)

    @property
    def changes_total(self) -> int:
        """Return the total number of reported changes in this eCR."""
        return self.changes_added + self.changes_updated + self.changes_deleted


@dataclass(frozen=True, slots=True)
class ManifestEntryResult:
    """Internal result returned after all entry-level writes succeed."""

    output_file: DIDOutputFile
    changes: tuple[Change, ...]
    telemetry: DocumentTelemetry


@dataclass(slots=True)
class BatchProcessingStats:
    """Statistics for one SQS batch processing attempt.

    Counts represent processing attempts, not unique manifests or documents.
    Whole-batch SQS retries can count previously successful work again.
    """

    started_at: float = field(default_factory=time.monotonic)
    manifests_processed: int = 0
    manifests_failed: int = 0
    documents_processed: int = 0
    documents_failed: int = 0
    changes_added: int = 0
    changes_updated: int = 0
    changes_deleted: int = 0
    section_change_counts: Counter[str] = field(default_factory=Counter)
    encounter_counts: Counter[str] = field(default_factory=Counter)
    documents_processed_by_condition: Counter[ConditionCode] = field(
        default_factory=Counter
    )

    def record_document_processed(self, result: ManifestEntryResult) -> None:
        """Add a successfully processed document and its reported changes."""
        document = result.telemetry

        self.documents_processed += 1
        self.changes_added += document.changes_added
        self.changes_updated += document.changes_updated
        self.changes_deleted += document.changes_deleted
        self.encounter_counts[document.encounter_type] += 1
        for change in result.changes:
            if change.section_loinc_code is not None:
                self.section_change_counts[change.section_loinc_code] += 1

    @property
    def changes_total(self) -> int:
        """Return the total number of reported changes."""
        return self.changes_added + self.changes_updated + self.changes_deleted

    @property
    def duration_ms(self) -> float:
        """Return elapsed processing time in milliseconds."""
        return (time.monotonic() - self.started_at) * 1000


@contextmanager
def batch_telemetry() -> Iterator[BatchProcessingStats]:
    """Record aggregate telemetry when a batch finishes."""
    stats = BatchProcessingStats()
    try:
        yield stats
    finally:
        _record_processing_metrics(stats)
        _log_documents_processed_by_condition(stats)


@contextmanager
def track_manifest(stats: BatchProcessingStats) -> Iterator[None]:
    """Count a manifest as processed or failed w/o swallowing failures."""
    try:
        yield
    except Exception:
        stats.manifests_failed += 1
        raise
    else:
        stats.manifests_processed += 1


@contextmanager
def track_document(stats: BatchProcessingStats) -> Iterator[None]:
    """Count document failures."""
    try:
        yield
    except Exception:
        stats.documents_failed += 1
        raise


@contextmanager
def processing_stage(
    stage_name: str,
    persistence_id_with_index: str | None = None,
) -> Iterator[None]:
    """Raise a processing failure with its stage and document identifier."""
    try:
        yield
    except Exception as exc:
        _raise_processing_failure(stage_name, exc, persistence_id_with_index)


def log_doc_and_changes(result: ManifestEntryResult) -> None:
    """Log one completed document and each of its reported changes."""
    doc_fields = {
        "persistence_id_with_index": result.telemetry.persistence_id_with_index,
        "version_number": result.telemetry.version_number,
    }
    logger.info(
        "document_processed",
        extra={
            **doc_fields,
            "unique_condition_count": result.telemetry.unique_condition_count,
            "changes_added": result.telemetry.changes_added,
            "changes_updated": result.telemetry.changes_updated,
            "changes_deleted": result.telemetry.changes_deleted,
            "changes_total": result.telemetry.changes_total,
        },
    )

    for change in result.changes:
        logger.info(
            "xml_change",
            extra={
                **doc_fields,
                "change_type": change.changeType.value,
                "change_path": change_path_for_logging(change),
            },
        )


def _raise_processing_failure(
    stage: str,
    exc: Exception,
    persistence_id_with_index: str | None = None,
) -> Never:
    """Log bounded failure details and raise a privacy-safe retryable error."""
    extra = {
        "failure_stage": stage,
        "error_type": type(exc).__name__,
    }
    if persistence_id_with_index is not None:
        extra["persistence_id_with_index"] = persistence_id_with_index

    logger.error(
        "processing_failure",
        extra=extra,
        exc_info=False,
        stack_info=False,
    )
    raise InfraError(f"Processing failed during {stage}") from None


def _record_processing_metrics(stats: BatchProcessingStats) -> None:
    """Record metrics for one batch processing attempt."""
    metrics.add_dimension(name="environment", value=ENVIRONMENT)
    count_metrics = {
        "ManifestsProcessed": stats.manifests_processed,
        "ManifestsFailed": stats.manifests_failed,
        "DocumentsProcessed": stats.documents_processed,
        "DocumentsFailed": stats.documents_failed,
        "ChangesAdded": stats.changes_added,
        "ChangesUpdated": stats.changes_updated,
        "ChangesDeleted": stats.changes_deleted,
        "ChangesTotal": stats.changes_total,
    }
    for name, value in count_metrics.items():
        metrics.add_metric(name=name, unit=MetricUnit.Count, value=value)

    metrics.add_metric(
        name="BatchDurationMs",
        unit=MetricUnit.Milliseconds,
        value=stats.duration_ms,
    )

    default_dimensions = {
        "service": SERVICE_NAME,
        "environment": ENVIRONMENT,
    }
    for section_loinc_code, change_count in stats.section_change_counts.items():
        with single_metric(
            name="SectionChanges",
            unit=MetricUnit.Count,
            value=change_count,
            namespace=METRICS_NAMESPACE,
            default_dimensions=default_dimensions,
        ) as section_metric:
            section_metric.add_dimension(
                name="section_loinc_code", value=section_loinc_code
            )

    for encounter_type, encounter_count in stats.encounter_counts.items():
        with single_metric(
            name="EncountersProcessed",
            unit=MetricUnit.Count,
            value=encounter_count,
            namespace=METRICS_NAMESPACE,
            default_dimensions=default_dimensions,
        ) as encounter_metric:
            encounter_metric.add_dimension(name="encounter_type", value=encounter_type)


def _log_documents_processed_by_condition(stats: BatchProcessingStats) -> None:
    """Log documents processed by condition without manifest-entry identifiers.

    These batch records remain temporally linkable in the shared Lambda log stream;
    their longer-term privacy boundary is pending external guidance.
    """
    for condition, documents_processed_count in sorted(
        stats.documents_processed_by_condition.items()
    ):
        logger.info(
            "documents_processed_by_condition",
            extra={
                "condition_code": condition.code,
                "condition_code_system": condition.code_system,
                "documents_processed_count": documents_processed_count,
            },
        )
