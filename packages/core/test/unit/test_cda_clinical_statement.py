import pytest
from core.cda_clinical_statement import (
    CDA_CLINICAL_STATEMENT_LOCAL_NAMES,
    CDA_SINGLE_STATEMENT_WRAPPER_LOCAL_NAMES,
    clinical_statement_identity_element,
)
from helpers import HL7_NS, elem, find_one

EXPECTED_CDA_CLINICAL_STATEMENT_LOCAL_NAMES = frozenset(
    {
        "act",
        "observation",
        "encounter",
        "procedure",
        "substanceAdministration",
        "supply",
        "organizer",
        "observationMedia",
        "regionOfInterest",
    }
)
EXPECTED_CDA_SINGLE_STATEMENT_WRAPPER_LOCAL_NAMES = frozenset(
    {
        "entry",
        "entryRelationship",
        "component",
    }
)


def test_clinical_statement_local_name_constants_match_cda_statement_contract():
    assert (
        CDA_CLINICAL_STATEMENT_LOCAL_NAMES
        == EXPECTED_CDA_CLINICAL_STATEMENT_LOCAL_NAMES
    )
    assert (
        CDA_SINGLE_STATEMENT_WRAPPER_LOCAL_NAMES
        == EXPECTED_CDA_SINGLE_STATEMENT_WRAPPER_LOCAL_NAMES
    )


@pytest.mark.parametrize(
    "local_name",
    sorted(CDA_CLINICAL_STATEMENT_LOCAL_NAMES),
)
def test_clinical_statement_identity_returns_direct_statement_itself(local_name):
    statement = elem(
        f"""
        <{local_name} xmlns="{HL7_NS}"/>
        """
    )

    assert clinical_statement_identity_element(statement) is statement


@pytest.mark.parametrize(
    "wrapper_name",
    sorted(CDA_SINGLE_STATEMENT_WRAPPER_LOCAL_NAMES),
)
def test_clinical_statement_identity_unwraps_single_statement_wrappers(wrapper_name):
    wrapper = elem(
        f"""
        <{wrapper_name} xmlns="{HL7_NS}">
          <observation classCode="OBS" moodCode="EVN"/>
        </{wrapper_name}>
        """
    )
    observation_element = find_one(wrapper, "./hl7:observation")

    assert clinical_statement_identity_element(wrapper) is observation_element


@pytest.mark.parametrize(
    "wrapper_name",
    sorted(CDA_SINGLE_STATEMENT_WRAPPER_LOCAL_NAMES),
)
def test_clinical_statement_identity_does_not_unwrap_empty_statement_wrappers(
    wrapper_name,
):
    wrapper = elem(
        f"""
        <{wrapper_name} xmlns="{HL7_NS}">
          <id root="not-a-clinical-statement"/>
        </{wrapper_name}>
        """
    )

    assert clinical_statement_identity_element(wrapper) is None


def test_clinical_statement_identity_does_not_unwrap_multi_entry_container():
    section = elem(
        f"""
        <section xmlns="{HL7_NS}">
          <entry>
            <observation classCode="OBS" moodCode="EVN">
              <id root="first"/>
            </observation>
          </entry>
          <entry>
            <observation classCode="OBS" moodCode="EVN">
              <id root="second"/>
            </observation>
          </entry>
        </section>
        """
    )

    assert clinical_statement_identity_element(section) is None


def test_single_statement_wrapper_with_multiple_direct_statements_has_no_statement_identity():
    entry = elem(
        f"""
        <entry xmlns="{HL7_NS}">
          <observation classCode="OBS" moodCode="EVN">
            <id root="first"/>
          </observation>
          <observation classCode="OBS" moodCode="EVN">
            <id root="second"/>
          </observation>
        </entry>
        """
    )

    assert clinical_statement_identity_element(entry) is None


def test_organizer_uses_itself_for_clinical_statement_identity():
    organizer = elem(
        f"""
        <organizer xmlns="{HL7_NS}" classCode="BATTERY" moodCode="EVN">
          <id root="organizer-id" extension="1"/>
          <component>
            <observation classCode="OBS" moodCode="EVN">
              <id root="observation-id" extension="1"/>
            </observation>
          </component>
        </organizer>
        """
    )

    assert clinical_statement_identity_element(organizer) is organizer
