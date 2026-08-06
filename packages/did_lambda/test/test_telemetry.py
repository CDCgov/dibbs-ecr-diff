from uuid import UUID

import pytest
from core import Change, ChangeType
from did_lambda.models import DIDOutputFile
from did_lambda.telemetry import (
    BatchProcessingStats,
    DocumentTelemetry,
    ManifestEntryResult,
)


def make_change(change_type: ChangeType) -> Change:
    return Change(
        changeType=change_type,
        xpath="/ClinicalDocument/component",
        xpathDocumentId="document-id",
        actionabilityRuleId=UUID(int=0),
        actionabilityRuleDisplayName="test rule",
    )


def make_result(*changes: Change) -> ManifestEntryResult:
    return ManifestEntryResult(
        output_file=DIDOutputFile(
            eicr="DIDOutput/eicr.xml",
            rr="DIDOutput/rr.xml",
            setId="set-id",
            versionNumber=2,
            is_actionable=True,
        ),
        changes=changes,
        telemetry=DocumentTelemetry(version_number=2),
    )


def test_records_processed_documents_and_reported_change_types() -> None:
    stats = BatchProcessingStats()

    stats.record_document_processed(
        make_result(
            make_change(ChangeType.ADDED),
            make_change(ChangeType.UPDATED),
            make_change(ChangeType.UPDATED),
            make_change(ChangeType.DELETED),
        )
    )
    stats.record_document_processed(make_result())

    assert stats.documents_processed == 2
    assert stats.changes_added == 1
    assert stats.changes_updated == 2
    assert stats.changes_deleted == 1
    assert stats.changes_total == 4


def test_duration_ms_uses_monotonic_elapsed_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = BatchProcessingStats(started_at=10.0)
    monkeypatch.setattr("did_lambda.telemetry.time.monotonic", lambda: 10.125)

    assert stats.duration_ms == pytest.approx(125.0)
