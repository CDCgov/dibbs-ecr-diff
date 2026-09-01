import traceback
from dataclasses import fields

import pytest
from core import ChangeType
from did_lambda import telemetry
from did_lambda.telemetry import (
    BatchProcessingStats,
    DocumentTelemetry,
    ManifestEntryResult,
    _log_documents_processed_by_condition,
    _raise_application_error,
    _record_processing_metrics,
    log_doc_and_changes,
)
from did_lambda.telemetry_helpers import ConditionCode
from did_lambda.utils import ApplicationError

from .helpers import (
    emitted_metrics,
    make_change,
    make_result,
)


def test_document_telemetry_exposes_only_expected_fields() -> None:
    assert tuple(field.name for field in fields(DocumentTelemetry)) == (
        "persistence_id_with_index",
        "version_number",
        "encounter_type",
        "unique_condition_count",
        "changes_added",
        "changes_updated",
        "changes_deleted",
    )
    assert tuple(field.name for field in fields(ManifestEntryResult)) == (
        "output_file",
        "changes",
        "telemetry",
    )


def test_emits_aggregate_section_and_encounter_metrics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stats = BatchProcessingStats(
        manifests_processed=1,
        documents_processed=2,
        documents_failed=1,
        changes_added=3,
        changes_updated=4,
        changes_deleted=5,
    )
    stats.section_change_counts.update({"18776-5": 3, "10160-0": 2})
    stats.encounter_counts.update({"ambulatory": 2, "inpatient": 1})

    _record_processing_metrics(stats)
    telemetry.metrics.flush_metrics()

    emf_objects = emitted_metrics(capsys)
    aggregate = next(item for item in emf_objects if "BatchDurationMs" in item)
    metric_definitions = aggregate["_aws"]["CloudWatchMetrics"][0]

    assert metric_definitions["Namespace"] == telemetry.METRICS_NAMESPACE
    assert set(metric_definitions["Dimensions"][0]) == {"service", "environment"}
    assert {
        metric["Name"]: metric["Unit"] for metric in metric_definitions["Metrics"]
    } == {
        "ManifestsProcessed": "Count",
        "ManifestsFailed": "Count",
        "DocumentsProcessed": "Count",
        "DocumentsFailed": "Count",
        "ChangesAdded": "Count",
        "ChangesUpdated": "Count",
        "ChangesDeleted": "Count",
        "ChangesTotal": "Count",
        "BatchDurationMs": "Milliseconds",
    }
    assert aggregate["service"] == telemetry.SERVICE_NAME
    assert aggregate["environment"] == telemetry.ENVIRONMENT
    assert aggregate["ManifestsProcessed"] == [1.0]
    assert aggregate["ManifestsFailed"] == [0.0]
    assert aggregate["DocumentsProcessed"] == [2.0]
    assert aggregate["DocumentsFailed"] == [1.0]
    assert aggregate["ChangesAdded"] == [3.0]
    assert aggregate["ChangesUpdated"] == [4.0]
    assert aggregate["ChangesDeleted"] == [5.0]
    assert aggregate["ChangesTotal"] == [12.0]
    assert aggregate["BatchDurationMs"][0] >= 0

    section_metrics = {
        item["section_loinc_code"]: item
        for item in emf_objects
        if "SectionChanges" in item
    }
    assert set(section_metrics) == {"18776-5", "10160-0"}
    assert section_metrics["18776-5"]["SectionChanges"] == [3.0]
    assert section_metrics["10160-0"]["SectionChanges"] == [2.0]
    for item in section_metrics.values():
        metric_definition = item["_aws"]["CloudWatchMetrics"][0]
        assert metric_definition["Namespace"] == telemetry.METRICS_NAMESPACE
        assert metric_definition["Metrics"] == [
            {"Name": "SectionChanges", "Unit": "Count"}
        ]
        assert set(metric_definition["Dimensions"][0]) == {
            "service",
            "environment",
            "section_loinc_code",
        }
        assert item["service"] == telemetry.SERVICE_NAME
        assert item["environment"] == telemetry.ENVIRONMENT

    encounter_metrics = {
        item["encounter_type"]: item
        for item in emf_objects
        if "EncountersProcessed" in item
    }
    assert set(encounter_metrics) == {"ambulatory", "inpatient"}
    assert encounter_metrics["ambulatory"]["EncountersProcessed"] == [2.0]
    assert encounter_metrics["inpatient"]["EncountersProcessed"] == [1.0]
    for item in encounter_metrics.values():
        metric_definition = item["_aws"]["CloudWatchMetrics"][0]
        assert metric_definition["Namespace"] == telemetry.METRICS_NAMESPACE
        assert metric_definition["Metrics"] == [
            {"Name": "EncountersProcessed", "Unit": "Count"}
        ]
        assert set(metric_definition["Dimensions"][0]) == {
            "service",
            "environment",
            "encounter_type",
        }
        assert item["service"] == telemetry.SERVICE_NAME
        assert item["environment"] == telemetry.ENVIRONMENT


def test_logs_document_and_reported_changes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    result = make_result(
        make_change(
            ChangeType.UPDATED,
            xpath="/hl7:ClinicalDocument[1]/hl7:component[2]",
            is_actionable=False,
        ),
        unique_condition_count=3,
        version_number=2,
    )

    log_doc_and_changes(result)

    document_log = next(
        record for record in caplog.records if record.message == "document_processed"
    )
    assert vars(document_log)["persistence_id_with_index"] == "2026/id:0"
    assert vars(document_log)["version_number"] == 2
    assert vars(document_log)["unique_condition_count"] == 3
    assert vars(document_log)["changes_added"] == 0
    assert vars(document_log)["changes_updated"] == 1
    assert vars(document_log)["changes_deleted"] == 0
    assert vars(document_log)["changes_total"] == 1

    change_log = next(
        record for record in caplog.records if record.message == "xml_change"
    )
    assert vars(change_log)["persistence_id_with_index"] == "2026/id:0"
    assert vars(change_log)["version_number"] == 2
    assert vars(change_log)["change_type"] == "UPDATED"
    assert vars(change_log)["change_path"] == "/hl7:ClinicalDocument/hl7:component"
    assert "isActionable" not in vars(change_log)
    assert "changes_added" not in vars(change_log)
    assert "changes_updated" not in vars(change_log)
    assert "changes_deleted" not in vars(change_log)
    assert "changes_total" not in vars(change_log)


def test_logs_documents_processed_by_condition_without_document_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    condition = ConditionCode(code_system="2.16.840.1.113883.6.96", code="840539006")
    stats = BatchProcessingStats()
    stats.documents_processed_by_condition[condition] = 2
    caplog.set_level("INFO")

    _log_documents_processed_by_condition(stats)

    condition_log = next(
        record
        for record in caplog.records
        if record.message == "documents_processed_by_condition"
    )
    condition_fields = vars(condition_log)
    assert condition_fields["condition_code"] == condition.code
    assert condition_fields["condition_code_system"] == condition.code_system
    assert condition_fields["documents_processed_count"] == 2
    assert "persistence_id_with_index" not in condition_fields
    assert "version_number" not in condition_fields


def test_processing_failure_log_and_exception_exclude_sensitive_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_value = (
        "s3://bucket/patient.xml <ClinicalDocument>secret</ClinicalDocument>"
    )
    caplog.set_level("INFO")

    with pytest.raises(ApplicationError) as raised:
        _raise_application_error(
            "diff",
            ValueError(sensitive_value),
            persistence_id_with_index="2026/id:0",
        )

    failure_log = next(
        record for record in caplog.records if record.message == "processing_failure"
    )
    failure_fields = vars(failure_log)
    assert failure_fields["failure_stage"] == "diff"
    assert failure_fields["error_type"] == "ValueError"
    assert failure_fields["persistence_id_with_index"] == "2026/id:0"
    assert not failure_log.exc_info
    assert not failure_log.stack_info
    assert str(raised.value) == "Processing failed during diff"
    assert sensitive_value not in caplog.text
    assert sensitive_value not in "".join(traceback.format_exception(raised.value))


def test_records_processed_documents_and_reported_change_types() -> None:
    stats = BatchProcessingStats()

    stats.record_document_processed(
        make_result(
            make_change(ChangeType.ADDED, section_loinc_code="18776-5"),
            make_change(ChangeType.UPDATED, section_loinc_code="18776-5"),
            make_change(ChangeType.UPDATED),
            make_change(ChangeType.DELETED, section_loinc_code="10160-0"),
        )
    )
    stats.record_document_processed(make_result())

    assert stats.documents_processed == 2
    assert stats.changes_added == 1
    assert stats.changes_updated == 2
    assert stats.changes_deleted == 1
    assert stats.changes_total == 4
    assert stats.section_change_counts == {"18776-5": 2, "10160-0": 1}
    assert stats.encounter_counts == {"ambulatory": 2}


def test_records_non_actionable_changes_reported_by_diff_output() -> None:
    stats = BatchProcessingStats()

    stats.record_document_processed(
        make_result(
            make_change(
                ChangeType.UPDATED,
                section_loinc_code="18776-5",
                is_actionable=False,
            )
        )
    )

    assert stats.documents_processed == 1
    assert stats.changes_updated == 1
    assert stats.changes_total == 1
    assert stats.section_change_counts == {"18776-5": 1}


def test_duration_ms_uses_monotonic_elapsed_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = BatchProcessingStats(started_at=10.0)
    monkeypatch.setattr("did_lambda.telemetry.time.monotonic", lambda: 10.125)

    assert stats.duration_ms == pytest.approx(125.0)
