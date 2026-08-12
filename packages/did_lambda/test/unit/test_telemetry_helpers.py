from inspect import signature
from uuid import UUID

import pytest
from core import Change, ChangeType
from did_lambda.telemetry_helpers import (
    ConditionCode,
    change_path_for_logging,
    condition_codes_from_rr,
    encounter_type_from_eicr,
    make_persistence_id_with_index,
)
from lxml import etree


def test_persistence_id_with_index_combines_manifest_id_and_zero_based_index() -> None:
    persistence_id = "2026/08/12/550e8400-e29b-41d4-a716-446655440000"

    assert make_persistence_id_with_index(persistence_id, 0) == f"{persistence_id}:0"
    assert make_persistence_id_with_index(persistence_id, 1) != (
        make_persistence_id_with_index(persistence_id, 0)
    )
    assert make_persistence_id_with_index("2026/08/12/different", 0) != (
        make_persistence_id_with_index(persistence_id, 0)
    )
    assert make_persistence_id_with_index(persistence_id, 0) == (
        make_persistence_id_with_index(persistence_id, 0)
    )


def test_persistence_id_with_index_accepts_persistence_id_and_index() -> None:
    assert tuple(signature(make_persistence_id_with_index).parameters) == (
        "persistence_id",
        "index",
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
