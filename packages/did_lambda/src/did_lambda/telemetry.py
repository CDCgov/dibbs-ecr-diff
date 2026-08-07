"""Internal processing statistics and results for Lambda telemetry."""

import hashlib
import hmac
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field

from core import Change, ChangeType

from .models import DIDOutputFile

DOCUMENT_CORRELATION_KEY_HEX_LENGTH = 32
MIN_LOG_HASH_SALT_BYTES = 32
_NUMERIC_POSITION_PREDICATE = re.compile(r"\[\d+\]")


class TelemetryConfigurationError(RuntimeError):
    """Raised when required telemetry configuration is invalid."""


def change_path_for_logging(change: Change) -> str:
    """Return a structural change path without positional predicates."""
    return _NUMERIC_POSITION_PREDICATE.sub("", change.xpath)


def make_document_correlation_key(set_id: str, version_number: int) -> str:
    """Create a deterministic pseudonymous document correlation key."""
    salt_value = os.environ.get("LOG_HASH_SALT")
    if salt_value is None:
        raise TelemetryConfigurationError("LOG_HASH_SALT is required")

    salt = salt_value.encode("utf-8")
    if len(salt) < MIN_LOG_HASH_SALT_BYTES:
        raise TelemetryConfigurationError(
            "LOG_HASH_SALT must contain at least 32 bytes"
        )

    message = set_id.encode("utf-8") + b"\x00" + str(version_number).encode("ascii")
    return hmac.new(salt, message, hashlib.sha256).hexdigest()[
        :DOCUMENT_CORRELATION_KEY_HEX_LENGTH
    ]


@dataclass(frozen=True, slots=True)
class DocumentTelemetry:
    """Privacy-limited document metadata available to telemetry consumers."""

    document_correlation_key: str
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
