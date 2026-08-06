import importlib
import json
import os
import traceback
from types import SimpleNamespace
from unittest.mock import ANY, Mock, call

import pytest
from did_lambda.models import DIDInputFile, DIDInputManifest, DIDOutputFile
from did_lambda.telemetry import (
    BatchProcessingStats,
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


def make_result() -> ManifestEntryResult:
    return ManifestEntryResult(
        output_file=DIDOutputFile(
            eicr="DIDOutput/2026/id/jurisdiction/eicr.xml",
            rr="DIDOutput/2026/id/jurisdiction/rr.xml",
            setId="set-id",
            versionNumber=1,
            is_actionable=True,
        ),
        changes=(),
        telemetry=DocumentTelemetry(
            document_correlation_key=make_document_correlation_key("set-id", 1),
            version_number=1,
        ),
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
) -> None:
    lambda_module = load_lambda_module()
    configure_manifest_record(monkeypatch, lambda_module)
    monkeypatch.setattr(
        lambda_module, "process_manifest_entry", lambda *_args: make_result()
    )
    put_object = Mock()
    monkeypatch.setattr(lambda_module, "put_object", put_object)
    stats = BatchProcessingStats()

    lambda_module.process_sqs_record(SimpleNamespace(json_body={}), stats)

    assert stats.documents_processed == 1
    assert stats.documents_failed == 0
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


def test_process_manifest_entry_returns_only_after_entry_writes_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lambda_module = load_lambda_module()
    entry = make_entry()
    monkeypatch.setattr(lambda_module, "get_before_actionable_record", lambda *_: None)
    monkeypatch.setattr(lambda_module, "get_object_xml_tree", lambda *_: object())
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

    result = lambda_module.process_manifest_entry("bucket", "2026/id", entry)

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
    )
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
    monkeypatch.setattr(
        lambda_module, "process_manifest_entry", lambda *_args: make_result()
    )
    monkeypatch.setattr(
        lambda_module,
        "put_object",
        Mock(side_effect=RuntimeError(SENSITIVE_FAILURE_TEXT)),
    )
    stats = BatchProcessingStats()

    with pytest.raises(InfraError) as raised:
        lambda_module.process_sqs_record(SimpleNamespace(json_body={}), stats)

    assert stats.documents_processed == 1
    assert stats.documents_failed == 0
    assert_safe_processing_failure(
        caplog,
        raised,
        stage="completion_write",
        error_type="RuntimeError",
        document_correlation_key=None,
    )
