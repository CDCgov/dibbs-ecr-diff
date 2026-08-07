from dataclasses import fields
from inspect import signature
from uuid import UUID

import pytest
from core import Change, ChangeType
from did_lambda.models import DIDOutputFile
from did_lambda.telemetry import (
    BatchProcessingStats,
    ConditionCode,
    DocumentTelemetry,
    ManifestEntryResult,
    TelemetryConfigurationError,
    change_path_for_logging,
    condition_codes_from_rr,
    make_document_correlation_key,
)
from lxml import etree

TEST_LOG_HASH_SALT = "a" * 32


def make_change(
    change_type: ChangeType,
    xpath: str = "/ClinicalDocument/component",
    section_loinc_code: str | None = None,
) -> Change:
    return Change(
        changeType=change_type,
        xpath=xpath,
        xpathDocumentId="document-id",
        actionabilityRuleId=UUID(int=0),
        actionabilityRuleDisplayName="test rule",
        section_loinc_code=section_loinc_code,
    )


def make_result(
    *changes: Change,
) -> ManifestEntryResult:
    return ManifestEntryResult(
        output_file=DIDOutputFile(
            eicr="DIDOutput/eicr.xml",
            rr="DIDOutput/rr.xml",
            setId="set-id",
            versionNumber=2,
            is_actionable=True,
        ),
        changes=changes,
        telemetry=DocumentTelemetry(
            document_correlation_key="test-correlation-key",
            version_number=2,
        ),
    )


def test_document_correlation_key_matches_known_hmac_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_id = "sensitive-set-id"
    monkeypatch.setenv("LOG_HASH_SALT", TEST_LOG_HASH_SALT)

    key = make_document_correlation_key(set_id, 2)

    assert key == "7d0e891727b5704803d9b3ed86bc43a4"
    assert len(key) == 32
    assert set(key) <= set("0123456789abcdef")
    assert set_id not in key
    assert TEST_LOG_HASH_SALT not in key


def test_document_correlation_key_is_deterministic_and_identifier_specific(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_HASH_SALT", TEST_LOG_HASH_SALT)

    key = make_document_correlation_key("set-id", 2)

    assert make_document_correlation_key("set-id", 2) == key
    assert make_document_correlation_key("different-set-id", 2) != key
    assert make_document_correlation_key("set-id", 3) != key


def test_document_correlation_key_changes_with_salt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_HASH_SALT", "a" * 32)
    first_key = make_document_correlation_key("set-id", 2)

    monkeypatch.setenv("LOG_HASH_SALT", "b" * 32)
    second_key = make_document_correlation_key("set-id", 2)

    assert second_key != first_key


def test_document_correlation_key_requires_salt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOG_HASH_SALT", raising=False)

    with pytest.raises(TelemetryConfigurationError) as raised:
        make_document_correlation_key("set-id", 2)

    assert str(raised.value) == "LOG_HASH_SALT is required"


def test_document_correlation_key_rejects_short_salt_without_exposing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    short_salt = "sensitive-short-salt"
    monkeypatch.setenv("LOG_HASH_SALT", short_salt)

    with pytest.raises(TelemetryConfigurationError) as raised:
        make_document_correlation_key("set-id", 2)

    assert str(raised.value) == "LOG_HASH_SALT must contain at least 32 bytes"
    assert short_salt not in str(raised.value)


def test_document_telemetry_exposes_only_privacy_limited_fields() -> None:
    assert tuple(signature(make_document_correlation_key).parameters) == (
        "set_id",
        "version_number",
    )
    assert tuple(field.name for field in fields(DocumentTelemetry)) == (
        "document_correlation_key",
        "version_number",
        "unique_condition_count",
    )
    assert tuple(field.name for field in fields(ManifestEntryResult)) == (
        "output_file",
        "changes",
        "telemetry",
    )


def test_extracts_unique_coded_conditions_from_rr_condition_observations() -> None:
    rr_tree = etree.ElementTree(
        etree.fromstring(
            b"""
            <ClinicalDocument xmlns="urn:hl7-org:v3">
              <observation>
                <templateId root="2.16.840.1.113883.10.20.15.2.3.12"/>
                <value code="43692000" codeSystem="2.16.840.1.113883.6.96"/>
              </observation>
              <observation>
                <templateId root="2.16.840.1.113883.10.20.15.2.3.12"/>
                <value code="43692000" codeSystem="2.16.840.1.113883.6.96"/>
              </observation>
              <observation>
                <templateId root="2.16.840.1.113883.10.20.15.2.3.12"/>
                <value code="840539006" codeSystem="2.16.840.1.113883.6.96"/>
              </observation>
              <observation>
                <templateId root="unrelated-template"/>
                <value code="sensitive-unrelated-code" codeSystem="unknown"/>
              </observation>
              <observation>
                <templateId root="2.16.840.1.113883.10.20.15.2.3.12"/>
                <value code="missing-code-system"/>
              </observation>
              <observation>
                <templateId root="2.16.840.1.113883.10.20.15.2.3.12"/>
                <value code="patient name" codeSystem="not-an-oid"/>
              </observation>
            </ClinicalDocument>
            """
        )
    )

    assert condition_codes_from_rr(rr_tree) == (
        ConditionCode(code_system="2.16.840.1.113883.6.96", code="43692000"),
        ConditionCode(code_system="2.16.840.1.113883.6.96", code="840539006"),
    )


def test_change_path_for_logging_removes_positions_without_changing_output() -> None:
    original_path = "/hl7:ClinicalDocument[1]/hl7:component[2]/sdtc:deceasedInd[12]"
    change = make_change(ChangeType.UPDATED, xpath=original_path)

    logged_path = change_path_for_logging(change)

    assert logged_path == ("/hl7:ClinicalDocument/hl7:component/sdtc:deceasedInd")
    assert change.xpath == original_path
    assert change.model_dump()["xpath"] == original_path


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


def test_duration_ms_uses_monotonic_elapsed_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = BatchProcessingStats(started_at=10.0)
    monkeypatch.setattr("did_lambda.telemetry.time.monotonic", lambda: 10.125)

    assert stats.duration_ms == pytest.approx(125.0)
