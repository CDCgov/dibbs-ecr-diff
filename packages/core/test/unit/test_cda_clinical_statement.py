from core.cda_clinical_statement import _clinical_statement_for_identity
from core.cda_key_models import DirectChildIdElementSetKey, RootExtension
from core.cda_stable_key import stable_key
from helpers import HL7_NS, elem


def test_clinical_statement_identity_unwraps_single_statement_wrappers():
    for wrapper_name in ("entry", "entryRelationship", "component"):
        wrapper = elem(
            f"""
            <{wrapper_name} xmlns="{HL7_NS}">
              <observation classCode="OBS" moodCode="EVN"/>
            </{wrapper_name}>
            """
        )
        observation_element = wrapper.xpath(
            "./hl7:observation",
            namespaces={"hl7": HL7_NS},
        )[0]

        assert _clinical_statement_for_identity(wrapper) is observation_element


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

    assert _clinical_statement_for_identity(section) is None
    assert stable_key(section) is None


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

    assert _clinical_statement_for_identity(entry) is None
    assert stable_key(entry) is None


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

    assert _clinical_statement_for_identity(organizer) is organizer
    assert stable_key(organizer) == DirectChildIdElementSetKey(
        root_extensions=(RootExtension(root="organizer-id", extension="1"),),
    )
