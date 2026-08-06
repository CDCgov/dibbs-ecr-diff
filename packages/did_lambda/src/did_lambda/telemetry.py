"""Internal processing statistics and results for Lambda telemetry."""

import time
from collections import Counter
from dataclasses import dataclass, field

from core import Change, ChangeType

from .models import DIDOutputFile


@dataclass(frozen=True, slots=True)
class DocumentTelemetry:
    """Privacy-limited document metadata available to telemetry consumers."""

    version_number: int


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

    def record_document_processed(self, result: ManifestEntryResult) -> None:
        """Add a successfully processed document and its reported changes."""
        counts = Counter(change.changeType for change in result.changes)

        self.documents_processed += 1
        self.changes_added += counts[ChangeType.ADDED]
        self.changes_updated += counts[ChangeType.UPDATED]
        self.changes_deleted += counts[ChangeType.DELETED]

    @property
    def changes_total(self) -> int:
        """Return the total number of reported changes."""
        return self.changes_added + self.changes_updated + self.changes_deleted

    @property
    def duration_ms(self) -> float:
        """Return elapsed processing time in milliseconds."""
        return (time.monotonic() - self.started_at) * 1000
