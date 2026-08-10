from inspect import signature
from uuid import UUID

import pytest
from core import Change, ChangeType
from did_lambda.telemetry_helpers import (
    ConditionCode,
    TelemetryConfigurationError,
    change_path_for_logging,
    condition_codes_from_rr,
    encounter_type_from_eicr,
    make_document_correlation_key,
)
from lxml import etree

TEST_LOG_HASH_SALT = "a" * 32


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


def test_document_correlation_key_accepts_only_set_id_and_version() -> None:
    assert tuple(signature(make_document_correlation_key).parameters) == (
        "set_id",
        "version_number",
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


@pytest.mark.parametrize(
    ("code_system", "code", "expected"),
    [
        ("2.16.840.1.113883.5.4", "AMB", "ambulatory"),
        ("2.16.840.1.113883.5.4", "EMER", "emergency"),
        ("2.16.840.1.113883.5.4", "IMP", "inpatient"),
        ("2.16.840.1.113883.5.4", "ACUTE", "inpatient"),
        ("2.16.840.1.113883.5.4", "NONAC", "inpatient"),
        ("2.16.840.1.113883.5.4", "OBSENC", "observation"),
        ("2.16.840.1.113883.5.4", "PRENC", "preadmission"),
        ("2.16.840.1.113883.5.4", "SS", "short_stay"),
        ("2.16.840.1.113883.5.4", "HH", "home_health"),
        ("2.16.840.1.113883.5.4", "FLD", "field"),
        ("2.16.840.1.113883.5.4", "VR", "virtual"),
        ("2.16.840.1.114222.4.5.274", "PHC2237", "external_historical"),
        ("2.16.840.1.113883.5.4", "UNSUPPORTED", "other"),
        ("9.9.9", "radioactive-encounter-value", "other"),
    ],
)
def test_extracts_bounded_encounter_type_from_eicr_header(
    code_system: str, code: str, expected: str
) -> None:
    eicr_tree = etree.ElementTree(
        etree.fromstring(
            f"""
            <ClinicalDocument xmlns="urn:hl7-org:v3">
              <componentOf>
                <encompassingEncounter>
                  <code code="{code}" codeSystem="{code_system}"/>
                </encompassingEncounter>
              </componentOf>
            </ClinicalDocument>
            """.encode()
        )
    )

    assert encounter_type_from_eicr(eicr_tree) == expected


@pytest.mark.parametrize(
    "code_element",
    [
        "",
        '<code nullFlavor="UNK"/>',
        '<code code="AMB"/>',
        '<code codeSystem="2.16.840.1.113883.5.4"/>',
    ],
)
def test_missing_encounter_code_data_is_unknown(code_element: str) -> None:
    eicr_tree = etree.ElementTree(
        etree.fromstring(
            f"""
            <ClinicalDocument xmlns="urn:hl7-org:v3">
              <componentOf>
                <encompassingEncounter>{code_element}</encompassingEncounter>
              </componentOf>
            </ClinicalDocument>
            """.encode()
        )
    )

    assert encounter_type_from_eicr(eicr_tree) == "unknown"


def test_change_path_for_logging_removes_positions_without_changing_output() -> None:
    original_path = "/hl7:ClinicalDocument[1]/hl7:component[2]/sdtc:deceasedInd[12]"
    change = Change(
        changeType=ChangeType.UPDATED,
        xpath=original_path,
        xpathDocumentId="document-id",
        actionabilityRuleId=UUID(int=0),
        actionabilityRuleDisplayName="test rule",
    )

    logged_path = change_path_for_logging(change)

    assert logged_path == "/hl7:ClinicalDocument/hl7:component/sdtc:deceasedInd"
    assert change.xpath == original_path
    assert change.model_dump()["xpath"] == original_path
