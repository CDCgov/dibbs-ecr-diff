"""Internal processing statistics and results for Lambda telemetry."""

import hashlib
import hmac
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field

from core import Change, ChangeType
from core.constants import NAMESPACES
from lxml.etree import ElementTree

from .models import DIDOutputFile

DOCUMENT_CORRELATION_KEY_HEX_LENGTH = 32
MIN_LOG_HASH_SALT_BYTES = 32
_NUMERIC_POSITION_PREDICATE = re.compile(r"\[\d+\]")
_RR_CONDITION_OBSERVATION_TEMPLATE_ID = "2.16.840.1.113883.10.20.15.2.3.12"
_RR_CONDITION_VALUE_XPATH = (
    ".//hl7:observation[hl7:templateId[@root="
    f"'{_RR_CONDITION_OBSERVATION_TEMPLATE_ID}'"
    "]]/hl7:value"
)
_CONDITION_CODE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_CODE_SYSTEM_OID_PATTERN = re.compile(r"\d+(?:\.\d+)+")
_MAX_CODE_SYSTEM_OID_LENGTH = 128


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


@dataclass(frozen=True, order=True, slots=True)
class ConditionCode:
    """A condition code without document-identifying context."""

    code_system: str
    code: str


def condition_codes_from_rr(rr_tree: ElementTree) -> tuple[ConditionCode, ...]:
    """Return unique coded conditions from RR condition observations."""
    conditions: set[ConditionCode] = set()
    for value in rr_tree.xpath(_RR_CONDITION_VALUE_XPATH, namespaces=NAMESPACES):
        code = value.get("code")
        code_system = value.get("codeSystem")
        if code is None or code_system is None:
            continue

        code = code.strip()
        code_system = code_system.strip()
        if (
            _CONDITION_CODE_PATTERN.fullmatch(code)
            and len(code_system) <= _MAX_CODE_SYSTEM_OID_LENGTH
            and _CODE_SYSTEM_OID_PATTERN.fullmatch(code_system)
        ):
            conditions.add(ConditionCode(code_system=code_system, code=code))

    return tuple(sorted(conditions))


@dataclass(frozen=True, slots=True)
class DocumentTelemetry:
    """Privacy-limited document metadata available to telemetry consumers."""

    document_correlation_key: str
    version_number: int
    unique_condition_count: int = 0


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
    doc_processing_attempts_by_condition: Counter[ConditionCode] = field(
        default_factory=Counter
    )

    def record_document_processed(self, result: ManifestEntryResult) -> None:
        """Add a successfully processed document and its reported changes."""
        counts = Counter(change.changeType for change in result.changes)

        self.documents_processed += 1
        self.changes_added += counts[ChangeType.ADDED]
        self.changes_updated += counts[ChangeType.UPDATED]
        self.changes_deleted += counts[ChangeType.DELETED]
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
