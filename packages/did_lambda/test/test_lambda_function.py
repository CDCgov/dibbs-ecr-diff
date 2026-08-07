import importlib
import json
import os
import traceback
from collections import Counter
from types import SimpleNamespace
from unittest.mock import ANY, Mock, call
from uuid import UUID

import pytest
from core import Change, ChangeType
from did_lambda.models import DIDInputFile, DIDInputManifest, DIDOutputFile
from did_lambda.telemetry import (
    BatchProcessingStats,
    ConditionCode,
    DocumentTelemetry,
    ManifestEntryResult,
    TelemetryConfigurationError,
    make_document_correlation_key,
)
from did_lambda.utils import InfraError

TEST_LOG_HASH_SALT = "a" * 32
SENSITIVE_TEST_VALUES = (
    "set-id",
    "document-id",
    "s3://bucket/patient.xml",
    "<ClinicalDocument>secret</ClinicalDocument>",
    '{"Records":["secret"]}',
)
SENSITIVE_FAILURE_TEXT = " ".join(SENSITIVE_TEST_VALUES)


@pytest.fixture(autouse=True)
def configure_log_hash_salt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_HASH_SALT", TEST_LOG_HASH_SALT)


def load_lambda_module():
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
    return importlib.import_module("did_lambda.lambda_function")


def make_entry() -> DIDInputFile:
    return DIDInputFile(
        eicr="DIDInput/2026/id/jurisdiction/eicr.xml",
        rr="DIDInput/2026/id/jurisdiction/rr.xml",
        setId="set-id",
        versionNumber=1,
    )


def make_result(
    *changes: Change,
    unique_condition_count: int = 0,
    encounter_type: str = "ambulatory",
) -> ManifestEntryResult:
    return ManifestEntryResult(
        output_file=DIDOutputFile(
            eicr="DIDOutput/2026/id/jurisdiction/eicr.xml",
            rr="DIDOutput/2026/id/jurisdiction/rr.xml",
            setId="set-id",
            versionNumber=1,
            is_actionable=True,
        ),
        changes=changes,
        telemetry=DocumentTelemetry(
            document_correlation_key=make_document_correlation_key("set-id", 1),
            version_number=1,
            encounter_type=encounter_type,
            unique_condition_count=unique_condition_count,
        ),
    )


def make_change(change_type: ChangeType, xpath: str) -> Change:
    return Change(
        changeType=change_type,
        xpath=xpath,
        xpathDocumentId="document-id",
        actionabilityRuleId=UUID(int=0),
        actionabilityRuleDisplayName="test rule",
        section_loinc_code="18776-5",
    )


def configure_manifest_record(monkeypatch: pytest.MonkeyPatch, lambda_module) -> None:
    event = SimpleNamespace(
        detail=SimpleNamespace(
            bucket=SimpleNamespace(name="bucket"),
            object=SimpleNamespace(key="DIDInput/2026/id"),
        )
    )
    monkeypatch.setattr(
        lambda_module, "S3EventBridgeNotificationEvent", lambda _body: event
    )
    monkeypatch.setattr(
        lambda_module,
        "get_input_manifest",
        lambda _bucket, _key: DIDInputManifest(Files=[make_entry()]),
    )


def assert_safe_processing_failure(
    caplog: pytest.LogCaptureFixture,
    raised,
    *,
    stage: str,
    error_type: str,
    document_correlation_key: str | None,
) -> None:
    failure_logs = [
        record for record in caplog.records if record.message == "processing_failure"
    ]
    assert len(failure_logs) == 1

    log = failure_logs[0]
    log_fields = vars(log)
    assert log_fields["failure_stage"] == stage
    assert log_fields["error_type"] == error_type
    assert not log.exc_info
    assert not log.stack_info

    if document_correlation_key is None:
        assert "document_correlation_key" not in log_fields
    else:
        assert log_fields["document_correlation_key"] == document_correlation_key

    assert str(raised.value) == f"Processing failed during {stage}"
    escaped_traceback = "".join(traceback.format_exception(raised.value))
    for sensitive_value in SENSITIVE_TEST_VALUES:
        assert sensitive_value not in caplog.text
        assert sensitive_value not in escaped_traceback


def emitted_metrics(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    """Return CloudWatch EMF objects emitted to standard output."""
    return [
        payload
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{") and "_aws" in (payload := json.loads(line))
    ]


def test_lambda_handler_emits_aggregate_section_and_encounter_metrics(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lambda_module = load_lambda_module()

    def process_record(_record, stats):
        stats.documents_processed = 2
        stats.documents_failed = 1
        stats.changes_added = 3
        stats.changes_updated = 4
        stats.changes_deleted = 5
        stats.section_change_counts.update({"18776-5": 3, "10160-0": 2})
        stats.encounter_counts.update({"ambulatory": 2, "inpatient": 1})

    monkeypatch.setattr(lambda_module, "process_sqs_record", process_record)

    response = lambda_module.lambda_handler({"Records": [{"body": "{}"}]}, None)

    assert response == {"statusCode": 200, "message": "OK"}
    emf_objects = emitted_metrics(capsys)
    aggregate = next(item for item in emf_objects if "BatchDurationMs" in item)
    metric_definitions = aggregate["_aws"]["CloudWatchMetrics"][0]

    assert metric_definitions["Namespace"] == lambda_module.METRICS_NAMESPACE
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
    assert aggregate["service"] == lambda_module.SERVICE_NAME
    assert aggregate["environment"] == lambda_module.ENVIRONMENT
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
        assert metric_definition["Namespace"] == lambda_module.METRICS_NAMESPACE
        assert metric_definition["Metrics"] == [
            {"Name": "SectionChanges", "Unit": "Count"}
        ]
        assert set(metric_definition["Dimensions"][0]) == {
            "service",
            "environment",
            "section_loinc_code",
        }
        assert item["service"] == lambda_module.SERVICE_NAME
        assert item["environment"] == lambda_module.ENVIRONMENT

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
        assert metric_definition["Namespace"] == lambda_module.METRICS_NAMESPACE
        assert metric_definition["Metrics"] == [
            {"Name": "EncountersProcessed", "Unit": "Count"}
        ]
        assert set(metric_definition["Dimensions"][0]) == {
            "service",
            "environment",
            "encounter_type",
        }
        assert item["service"] == lambda_module.SERVICE_NAME
        assert item["environment"] == lambda_module.ENVIRONMENT


def test_lambda_handler_logs_doc_processing_attempts_by_condition(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lambda_module = load_lambda_module()
    condition = ConditionCode(code_system="2.16.840.1.113883.6.96", code="840539006")
    caplog.set_level("INFO")

    def process_record(_record, stats):
        stats.doc_processing_attempts_by_condition[condition] = 2

    monkeypatch.setattr(lambda_module, "process_sqs_record", process_record)

    response = lambda_module.lambda_handler({"Records": [{"body": "{}"}]}, None)

    assert response == {"statusCode": 200, "message": "OK"}
    condition_logs = [
        record
        for record in caplog.records
        if record.message == "doc_processing_attempts_by_condition"
    ]
    assert len(condition_logs) == 1
    condition_fields = vars(condition_logs[0])
    assert condition_fields["condition_code"] == condition.code
    assert condition_fields["condition_code_system"] == condition.code_system
    assert condition_fields["doc_processing_attempt_count"] == 2
    assert "document_correlation_key" not in condition_fields
    assert "version_number" not in condition_fields


def test_lambda_handler_flushes_completed_metrics_when_later_manifest_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lambda_module = load_lambda_module()
    failure = InfraError("Processing failed during output_write")
    records_processed = 0

    def fail_record(_record, stats):
        nonlocal records_processed
        records_processed += 1
        if records_processed == 1:
            stats.documents_processed = 1
            stats.changes_added = 2
            stats.section_change_counts["18776-5"] = 2
            return

        stats.documents_failed = 1
        raise failure

    monkeypatch.setattr(lambda_module, "process_sqs_record", fail_record)

    with pytest.raises(InfraError) as raised:
        lambda_module.lambda_handler(
            {"Records": [{"body": "{}"}, {"body": "{}"}]}, None
        )

    assert raised.value is failure
    emf_objects = emitted_metrics(capsys)
    aggregate = next(item for item in emf_objects if "BatchDurationMs" in item)
    assert aggregate["ManifestsProcessed"] == [1.0]
    assert aggregate["ManifestsFailed"] == [1.0]
    assert aggregate["DocumentsProcessed"] == [1.0]
    assert aggregate["DocumentsFailed"] == [1.0]
    assert aggregate["ChangesAdded"] == [2.0]
    assert aggregate["ChangesTotal"] == [2.0]
    section_metric = next(item for item in emf_objects if "SectionChanges" in item)
    assert section_metric["section_loinc_code"] == "18776-5"
    assert section_metric["SectionChanges"] == [2.0]


def test_lambda_handler_emits_only_failure_metrics_for_failed_manifest(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    lambda_module = load_lambda_module()
    failure = InfraError("Processing failed during output_write")
    caplog.set_level("INFO")

    def fail_record(_record, stats):
        stats.documents_failed = 1
        raise failure

    monkeypatch.setattr(lambda_module, "process_sqs_record", fail_record)

    with pytest.raises(InfraError) as raised:
        lambda_module.lambda_handler({"Records": [{"body": "{}"}]}, None)

    assert raised.value is failure
    emf_objects = emitted_metrics(capsys)
    aggregate = next(item for item in emf_objects if "BatchDurationMs" in item)
    assert aggregate["ManifestsProcessed"] == [0.0]
    assert aggregate["ManifestsFailed"] == [1.0]
    assert aggregate["DocumentsProcessed"] == [0.0]
    assert aggregate["DocumentsFailed"] == [1.0]
    assert aggregate["ChangesTotal"] == [0.0]
    assert aggregate["BatchDurationMs"][0] >= 0
    assert all("SectionChanges" not in item for item in emf_objects)
    assert all("EncountersProcessed" not in item for item in emf_objects)
    assert all(
        record.message
        not in {
            "document_processed",
            "xml_change",
            "doc_processing_attempts_by_condition",
        }
        for record in caplog.records
    )


def test_lambda_handler_counts_successful_manifest_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lambda_module = load_lambda_module()
    observed_stats = []

    def process_record(_record, stats):
        observed_stats.append(stats)

    monkeypatch.setattr(lambda_module, "process_sqs_record", process_record)

    response = lambda_module.lambda_handler(
        {"Records": [{"body": "{}"}, {"body": "{}"}]}, None
    )

    assert response == {"statusCode": 200, "message": "OK"}
    assert len(observed_stats) == 2
    assert observed_stats[0] is observed_stats[1]
    assert observed_stats[0].manifests_processed == 2
    assert observed_stats[0].manifests_failed == 0


def test_lambda_handler_counts_failure_and_rethrows_same_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lambda_module = load_lambda_module()
    observed_stats = []
    failure = InfraError("Processing failed during manifest_load")

    def fail_record(_record, stats):
        observed_stats.append(stats)
        raise failure

    monkeypatch.setattr(lambda_module, "process_sqs_record", fail_record)

    with pytest.raises(InfraError) as raised:
        lambda_module.lambda_handler({"Records": [{"body": "{}"}]}, None)

    assert raised.value is failure
    assert len(observed_stats) == 1
    assert observed_stats[0].manifests_processed == 0
    assert observed_stats[0].manifests_failed == 1


def test_process_sqs_record_preserves_completion_manifest_schema(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lambda_module = load_lambda_module()
    caplog.set_level("INFO")
    configure_manifest_record(monkeypatch, lambda_module)
    stats = BatchProcessingStats()
    condition = ConditionCode(code_system="2.16.840.1.113883.6.96", code="840539006")

    def process_entry(_bucket, _persistence_id, _entry, condition_counts):
        condition_counts[condition] += 1
        return make_result()

    def write_completion(_bucket, _key, _body):
        assert stats.documents_processed == 0
        assert stats.encounter_counts == {}
        assert stats.doc_processing_attempts_by_condition == {}
        assert all(
            record.message not in {"document_processed", "xml_change"}
            for record in caplog.records
        )

    monkeypatch.setattr(lambda_module, "process_manifest_entry", process_entry)
    put_object = Mock(side_effect=write_completion)
    monkeypatch.setattr(lambda_module, "put_object", put_object)

    lambda_module.process_sqs_record(SimpleNamespace(json_body={}), stats)

    assert stats.documents_processed == 1
    assert stats.documents_failed == 0
    assert stats.encounter_counts == {"ambulatory": 1}
    assert stats.doc_processing_attempts_by_condition == {condition: 1}
    doc_log = next(
        record for record in caplog.records if record.message == "document_processed"
    )
    assert vars(doc_log)["unique_condition_count"] == 0
    assert all(record.message != "xml_change" for record in caplog.records)
    put_object.assert_called_once()
    bucket, key, body = put_object.call_args.args
    assert bucket == "bucket"
    assert key == "DIDComplete/2026/id"
    assert json.loads(body) == {
        "Files": [
            {
                "eicr": "DIDOutput/2026/id/jurisdiction/eicr.xml",
                "rr": "DIDOutput/2026/id/jurisdiction/rr.xml",
                "setId": "set-id",
                "versionNumber": 1,
                "eicr_diff_output": None,
                "is_actionable": True,
            }
        ]
    }


def test_process_sqs_record_counts_failure_and_rethrows_same_exception(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lambda_module = load_lambda_module()
    configure_manifest_record(monkeypatch, lambda_module)
    failure = InfraError("Processing failed during output_write")

    def fail_entry(*_args):
        raise failure

    monkeypatch.setattr(lambda_module, "process_manifest_entry", fail_entry)
    put_object = Mock()
    monkeypatch.setattr(lambda_module, "put_object", put_object)
    stats = BatchProcessingStats()

    with pytest.raises(InfraError) as raised:
        lambda_module.process_sqs_record(SimpleNamespace(json_body={}), stats)

    assert raised.value is failure
    assert stats.documents_processed == 0
    assert stats.documents_failed == 1
    put_object.assert_not_called()
    assert all(
        record.message not in {"document_processed", "xml_change"}
        for record in caplog.records
    )


def test_process_sqs_record_discards_pending_telemetry_on_entry_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lambda_module = load_lambda_module()
    configure_manifest_record(monkeypatch, lambda_module)
    monkeypatch.setattr(
        lambda_module,
        "get_input_manifest",
        lambda _bucket, _key: DIDInputManifest(Files=[make_entry(), make_entry()]),
    )
    failure = InfraError("Processing failed during output_write")
    condition = ConditionCode(code_system="2.16.840.1.113883.6.96", code="840539006")
    successful_result = make_result(
        make_change(
            ChangeType.ADDED,
            "/hl7:ClinicalDocument[1]/hl7:component[1]/hl7:section[1]",
        )
    )
    entry_attempts = 0
    pending_condition_counts = None

    def process_entry(_bucket, _persistence_id, _entry, condition_counts):
        nonlocal entry_attempts, pending_condition_counts
        entry_attempts += 1
        pending_condition_counts = condition_counts
        if entry_attempts == 1:
            condition_counts[condition] += 1
            return successful_result
        raise failure

    monkeypatch.setattr(lambda_module, "process_manifest_entry", process_entry)
    put_object = Mock()
    monkeypatch.setattr(lambda_module, "put_object", put_object)
    caplog.set_level("INFO")
    stats = BatchProcessingStats()

    with pytest.raises(InfraError) as raised:
        lambda_module.process_sqs_record(SimpleNamespace(json_body={}), stats)

    assert raised.value is failure
    assert pending_condition_counts == {condition: 1}
    assert stats.documents_processed == 0
    assert stats.documents_failed == 1
    assert stats.changes_total == 0
    assert stats.section_change_counts == {}
    assert stats.encounter_counts == {}
    assert stats.doc_processing_attempts_by_condition == {}
    put_object.assert_not_called()
    assert all(
        record.message not in {"document_processed", "xml_change"}
        for record in caplog.records
    )


def test_process_sqs_record_logs_completed_document_and_reported_changes(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lambda_module = load_lambda_module()
    configure_manifest_record(monkeypatch, lambda_module)
    result = make_result(
        make_change(
            ChangeType.ADDED,
            "/hl7:ClinicalDocument[1]/hl7:component[2]/hl7:section[1]",
        ),
        make_change(
            ChangeType.UPDATED,
            "/hl7:ClinicalDocument[1]/hl7:component[3]/hl7:section[2]",
        ),
        make_change(
            ChangeType.DELETED,
            "/hl7:ClinicalDocument[1]/hl7:component[4]/hl7:section[3]",
        ),
        unique_condition_count=1,
    )
    monkeypatch.setattr(lambda_module, "process_manifest_entry", lambda *_args: result)
    monkeypatch.setattr(lambda_module, "put_object", Mock())
    caplog.set_level("INFO")

    lambda_module.process_sqs_record(
        SimpleNamespace(json_body={}), BatchProcessingStats()
    )

    doc_logs = [
        record for record in caplog.records if record.message == "document_processed"
    ]
    change_logs = [
        record for record in caplog.records if record.message == "xml_change"
    ]
    assert len(doc_logs) == 1
    doc_fields = vars(doc_logs[0])
    assert doc_fields["document_correlation_key"] == (
        result.telemetry.document_correlation_key
    )
    assert doc_fields["version_number"] == 1
    assert doc_fields["unique_condition_count"] == 1
    assert "condition_code" not in doc_fields
    assert "condition_code_system" not in doc_fields
    assert "encounter_type" not in doc_fields

    assert [vars(record)["change_type"] for record in change_logs] == [
        "ADDED",
        "UPDATED",
        "DELETED",
    ]
    assert [vars(record)["change_path"] for record in change_logs] == [
        "/hl7:ClinicalDocument/hl7:component/hl7:section",
        "/hl7:ClinicalDocument/hl7:component/hl7:section",
        "/hl7:ClinicalDocument/hl7:component/hl7:section",
    ]
    for record in change_logs:
        fields = vars(record)
        assert fields["document_correlation_key"] == (
            result.telemetry.document_correlation_key
        )
        assert fields["version_number"] == 1
        assert "unique_condition_count" not in fields
        assert "condition_code" not in fields
        assert "condition_code_system" not in fields
        assert "section_loinc_code" not in fields
        assert "encounter_type" not in fields

    logged_fields = repr([vars(record) for record in doc_logs + change_logs])
    assert "radioactive-condition-code" not in logged_fields
    assert "document-id" not in logged_fields
    assert "set-id" not in logged_fields
    assert "[1]" not in logged_fields


def test_process_manifest_entry_returns_only_after_entry_writes_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lambda_module = load_lambda_module()
    entry = make_entry()
    eicr_tree = object()
    rr_tree = object()
    condition_codes = (
        ConditionCode(code_system="2.16.840.1.113883.6.96", code="840539006"),
    )
    doc_processing_attempts_by_condition: Counter[ConditionCode] = Counter()
    monkeypatch.setattr(lambda_module, "get_before_actionable_record", lambda *_: None)
    monkeypatch.setattr(
        lambda_module,
        "get_object_xml_tree",
        Mock(side_effect=[eicr_tree, rr_tree]),
    )
    extract_conditions = Mock(return_value=condition_codes)
    monkeypatch.setattr(lambda_module, "condition_codes_from_rr", extract_conditions)
    extract_encounter_type = Mock(return_value="ambulatory")
    monkeypatch.setattr(
        lambda_module, "encounter_type_from_eicr", extract_encounter_type
    )
    monkeypatch.setattr(lambda_module, "jurisdiction_id_from_key", lambda *_: "jur")
    monkeypatch.setattr(lambda_module, "get_augmented_eicr", lambda *_: b"eicr")
    monkeypatch.setattr(lambda_module, "get_augmented_rr", lambda *_: b"rr")

    operations = Mock()
    put_eicr_record = Mock()
    put_object = Mock()
    operations.attach_mock(put_eicr_record, "put_eicr_record")
    operations.attach_mock(put_object, "put_object")
    monkeypatch.setattr(lambda_module, "put_eicr_record", put_eicr_record)
    monkeypatch.setattr(lambda_module, "put_object", put_object)

    result = lambda_module.process_manifest_entry(
        "bucket", "2026/id", entry, doc_processing_attempts_by_condition
    )

    assert result.output_file == DIDOutputFile(
        eicr="DIDOutput/2026/id/jurisdiction/eicr.xml",
        rr="DIDOutput/2026/id/jurisdiction/rr.xml",
        setId="set-id",
        versionNumber=1,
        is_actionable=True,
    )
    assert result.changes == ()
    assert result.telemetry == DocumentTelemetry(
        document_correlation_key=make_document_correlation_key("set-id", 1),
        version_number=1,
        encounter_type="ambulatory",
        unique_condition_count=1,
    )
    assert not hasattr(result, "condition_codes")
    assert doc_processing_attempts_by_condition == {condition_codes[0]: 1}
    extract_conditions.assert_called_once_with(rr_tree)
    extract_encounter_type.assert_called_once_with(eicr_tree)
    assert operations.mock_calls == [
        call.put_eicr_record(
            {
                "setId": "set-id",
                "versionNumber": 1,
                "s3Key": entry.eicr,
                "s3KeyRR": entry.rr,
                "s3KeyDiffOutput": None,
                "processedAt": ANY,
                "isActionable": True,
                "comparedToVersion": None,
            }
        ),
        call.put_object("bucket", "DIDOutput/2026/id/jurisdiction/eicr.xml", b"eicr"),
        call.put_object("bucket", "DIDOutput/2026/id/jurisdiction/rr.xml", b"rr"),
    ]


def test_process_manifest_entry_propagates_final_write_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lambda_module = load_lambda_module()
    entry = make_entry()
    monkeypatch.setattr(lambda_module, "get_before_actionable_record", lambda *_: None)
    monkeypatch.setattr(lambda_module, "get_object_xml_tree", lambda *_: object())
    monkeypatch.setattr(lambda_module, "condition_codes_from_rr", lambda *_: ())
    monkeypatch.setattr(
        lambda_module, "encounter_type_from_eicr", lambda *_: "ambulatory"
    )
    monkeypatch.setattr(lambda_module, "jurisdiction_id_from_key", lambda *_: "jur")
    monkeypatch.setattr(lambda_module, "get_augmented_eicr", lambda *_: b"eicr")
    monkeypatch.setattr(lambda_module, "get_augmented_rr", lambda *_: b"rr")
    monkeypatch.setattr(lambda_module, "put_eicr_record", Mock())
    failure = RuntimeError(SENSITIVE_FAILURE_TEXT)
    put_object = Mock(side_effect=[None, failure])
    monkeypatch.setattr(lambda_module, "put_object", put_object)

    with pytest.raises(InfraError) as raised:
        lambda_module.process_manifest_entry("bucket", "2026/id", entry)

    assert put_object.call_count == 2
    assert_safe_processing_failure(
        caplog,
        raised,
        stage="output_write",
        error_type="RuntimeError",
        document_correlation_key=make_document_correlation_key("set-id", 1),
    )


def test_process_manifest_entry_rejects_missing_salt_before_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lambda_module = load_lambda_module()
    monkeypatch.delenv("LOG_HASH_SALT")
    get_before_actionable_record = Mock()
    get_object_xml_tree = Mock()
    put_eicr_record = Mock()
    put_object = Mock()
    monkeypatch.setattr(
        lambda_module, "get_before_actionable_record", get_before_actionable_record
    )
    monkeypatch.setattr(lambda_module, "get_object_xml_tree", get_object_xml_tree)
    monkeypatch.setattr(lambda_module, "put_eicr_record", put_eicr_record)
    monkeypatch.setattr(lambda_module, "put_object", put_object)

    with pytest.raises(InfraError) as raised:
        lambda_module.process_manifest_entry("bucket", "2026/id", make_entry())

    get_before_actionable_record.assert_not_called()
    get_object_xml_tree.assert_not_called()
    put_eicr_record.assert_not_called()
    put_object.assert_not_called()
    assert_safe_processing_failure(
        caplog,
        raised,
        stage="telemetry_config",
        error_type=TelemetryConfigurationError.__name__,
        document_correlation_key=None,
    )


@pytest.mark.parametrize(
    "stage",
    ["document_load", "diff", "augmentation"],
)
def test_process_manifest_entry_sanitizes_each_processing_stage(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    stage: str,
) -> None:
    lambda_module = load_lambda_module()
    before_record = SimpleNamespace(versionNumber=0, s3Key="sensitive-prior-key")
    monkeypatch.setattr(lambda_module, "get_before_actionable_record", lambda *_: None)
    monkeypatch.setattr(lambda_module, "get_object_xml_tree", lambda *_: object())
    monkeypatch.setattr(lambda_module, "condition_codes_from_rr", lambda *_: ())
    monkeypatch.setattr(
        lambda_module, "encounter_type_from_eicr", lambda *_: "ambulatory"
    )
    monkeypatch.setattr(lambda_module, "jurisdiction_id_from_key", lambda *_: "jur")
    monkeypatch.setattr(lambda_module, "get_augmented_eicr", lambda *_: b"eicr")
    monkeypatch.setattr(lambda_module, "get_augmented_rr", lambda *_: b"rr")
    monkeypatch.setattr(lambda_module, "put_eicr_record", Mock())
    monkeypatch.setattr(lambda_module, "put_object", Mock())

    if stage == "document_load":
        monkeypatch.setattr(
            lambda_module,
            "get_before_actionable_record",
            Mock(side_effect=RuntimeError(SENSITIVE_FAILURE_TEXT)),
        )
    elif stage == "diff":
        monkeypatch.setattr(
            lambda_module, "get_before_actionable_record", lambda *_: before_record
        )
        monkeypatch.setattr(
            lambda_module,
            "diff_xml",
            Mock(side_effect=RuntimeError(SENSITIVE_FAILURE_TEXT)),
        )
    else:
        monkeypatch.setattr(
            lambda_module,
            "get_augmented_eicr",
            Mock(side_effect=RuntimeError(SENSITIVE_FAILURE_TEXT)),
        )

    with pytest.raises(InfraError) as raised:
        lambda_module.process_manifest_entry("bucket", "2026/id", make_entry())

    assert_safe_processing_failure(
        caplog,
        raised,
        stage=stage,
        error_type="RuntimeError",
        document_correlation_key=make_document_correlation_key("set-id", 1),
    )


def test_process_sqs_record_sanitizes_manifest_load_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lambda_module = load_lambda_module()
    monkeypatch.setattr(
        lambda_module,
        "S3EventBridgeNotificationEvent",
        Mock(side_effect=RuntimeError(SENSITIVE_FAILURE_TEXT)),
    )

    with pytest.raises(InfraError) as raised:
        lambda_module.process_sqs_record(SimpleNamespace(json_body={}))

    assert_safe_processing_failure(
        caplog,
        raised,
        stage="manifest_load",
        error_type="RuntimeError",
        document_correlation_key=None,
    )


def test_process_sqs_record_sanitizes_completion_write_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lambda_module = load_lambda_module()
    configure_manifest_record(monkeypatch, lambda_module)
    condition = ConditionCode(code_system="2.16.840.1.113883.6.96", code="840539006")
    result = make_result(
        make_change(
            ChangeType.ADDED,
            "/hl7:ClinicalDocument[1]/hl7:component[1]/hl7:section[1]",
        )
    )

    def process_entry(_bucket, _persistence_id, _entry, condition_counts):
        condition_counts[condition] += 1
        return result

    monkeypatch.setattr(lambda_module, "process_manifest_entry", process_entry)
    monkeypatch.setattr(
        lambda_module,
        "put_object",
        Mock(side_effect=RuntimeError(SENSITIVE_FAILURE_TEXT)),
    )
    stats = BatchProcessingStats()

    with pytest.raises(InfraError) as raised:
        lambda_module.process_sqs_record(SimpleNamespace(json_body={}), stats)

    assert stats.documents_processed == 0
    assert stats.documents_failed == 0
    assert stats.changes_total == 0
    assert stats.section_change_counts == {}
    assert stats.encounter_counts == {}
    assert stats.doc_processing_attempts_by_condition == {}
    assert all(
        record.message not in {"document_processed", "xml_change"}
        for record in caplog.records
    )
    assert_safe_processing_failure(
        caplog,
        raised,
        stage="completion_write",
        error_type="RuntimeError",
        document_correlation_key=None,
    )
