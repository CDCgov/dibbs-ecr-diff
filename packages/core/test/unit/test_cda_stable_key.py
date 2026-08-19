from core.cda.key_models import (
    CodeElement,
    CodeKey,
    DirectChildCodeElementSetKey,
    DirectChildIdElementSetKey,
    DirectChildTemplateIdElementSetKey,
    DirectIdAttributeKey,
    NestedClinicalStatementCodeElementSetKey,
    NestedClinicalStatementIdAttributeKey,
    NestedClinicalStatementIdElementSetKey,
    NestedClinicalStatementTemplateIdElementSetKey,
    NestedSectionIdElementSetKey,
    NestedSectionTemplateIdElementSetKey,
    RootExtension,
    RootExtensionKey,
)
from core.cda.stable_key import (
    STABLE_KEY_RANKS,
    stable_key_candidates,
)
from core.cda.stable_key import (
    highest_ranked_stable_key as stable_key,
)
from helpers import HL7_NS, elem, observation


def test_stable_key_uses_order_insensitive_direct_template_id_root_extensions():
    first = observation(
        """
        <templateId root="2" extension="b"/>
        <templateId root="1"/>
        """
    )
    second = observation(
        """
        <templateId root="1"/>
        <templateId root="2" extension="b"/>
        """
    )

    assert stable_key(first) == stable_key(second)
    assert stable_key(first) == DirectChildTemplateIdElementSetKey(
        root_extensions=(
            RootExtension(root="1"),
            RootExtension(root="2", extension="b"),
        ),
    )


def test_stable_key_does_not_use_weak_attributes_as_key():
    element = elem(
        f"""
        <observation xmlns="{HL7_NS}" classCode="OBS" moodCode="EVN"/>
        """
    )

    assert stable_key(element) is None


def test_stable_key_candidates_contains_every_ranked_candidate():
    element = observation('<id root="id-root"/><templateId root="template-root"/>')

    candidates = stable_key_candidates(element)

    assert list(STABLE_KEY_RANKS) == sorted(STABLE_KEY_RANKS)
    assert tuple(candidates) == STABLE_KEY_RANKS
    assert set(candidates) == set(STABLE_KEY_RANKS)
    assert candidates[STABLE_KEY_RANKS.ID_ATTRIBUTE_RANK] is None
    assert candidates[STABLE_KEY_RANKS.DIRECT_CHILD_ID_RANK] is not None
    assert candidates[STABLE_KEY_RANKS.DIRECT_CHILD_TEMPLATE_ID_RANK] is not None
    assert all(candidate_name in candidates for candidate_name in STABLE_KEY_RANKS)
    assert STABLE_KEY_RANKS.ID_ATTRIBUTE_RANK == 1
    assert STABLE_KEY_RANKS.CLINICAL_STATEMENT_TEMPLATE_ID_RANK == 12


def test_stable_key_candidates_populates_each_candidate_type():
    candidate_cases = (
        (
            STABLE_KEY_RANKS.ID_ATTRIBUTE_RANK,
            elem(f'<observation xmlns="{HL7_NS}" ID="element-id"/>'),
            DirectIdAttributeKey,
        ),
        (
            STABLE_KEY_RANKS.ROOT_EXTENSION_RANK,
            elem(f'<id xmlns="{HL7_NS}" root="root"/>'),
            RootExtensionKey,
        ),
        (
            STABLE_KEY_RANKS.CODE_RANK,
            elem(f'<code xmlns="{HL7_NS}" code="code" codeSystem="system"/>'),
            CodeKey,
        ),
        (
            STABLE_KEY_RANKS.DIRECT_CHILD_ID_RANK,
            observation('<id root="child-id"/>'),
            DirectChildIdElementSetKey,
        ),
        (
            STABLE_KEY_RANKS.CLINICAL_STATEMENT_ID_ATTRIBUTE_RANK,
            elem(f'<entry xmlns="{HL7_NS}"><observation ID="statement-id"/></entry>'),
            NestedClinicalStatementIdAttributeKey,
        ),
        (
            STABLE_KEY_RANKS.CLINICAL_STATEMENT_ID_RANK,
            elem(
                f'<entry xmlns="{HL7_NS}"><observation><id root="statement-id"/>'
                "</observation></entry>"
            ),
            NestedClinicalStatementIdElementSetKey,
        ),
        (
            STABLE_KEY_RANKS.DIRECT_CHILD_CODE_RANK,
            observation('<code code="child-code" codeSystem="system"/>'),
            DirectChildCodeElementSetKey,
        ),
        (
            STABLE_KEY_RANKS.CLINICAL_STATEMENT_CODE_RANK,
            elem(
                f'<entry xmlns="{HL7_NS}"><observation><code code="statement-code" '
                'codeSystem="system"/></observation></entry>'
            ),
            NestedClinicalStatementCodeElementSetKey,
        ),
        (
            STABLE_KEY_RANKS.SECTION_ID_RANK,
            elem(
                f'<component xmlns="{HL7_NS}"><section><id root="section-id"/>'
                "</section></component>"
            ),
            NestedSectionIdElementSetKey,
        ),
        (
            STABLE_KEY_RANKS.DIRECT_CHILD_TEMPLATE_ID_RANK,
            observation('<templateId root="child-template"/>'),
            DirectChildTemplateIdElementSetKey,
        ),
        (
            STABLE_KEY_RANKS.SECTION_TEMPLATE_ID_RANK,
            elem(
                f'<component xmlns="{HL7_NS}"><section><templateId root="section-template"/>'
                "</section></component>"
            ),
            NestedSectionTemplateIdElementSetKey,
        ),
        (
            STABLE_KEY_RANKS.CLINICAL_STATEMENT_TEMPLATE_ID_RANK,
            elem(
                f'<entry xmlns="{HL7_NS}"><observation><templateId root="statement-template"/>'
                "</observation></entry>"
            ),
            NestedClinicalStatementTemplateIdElementSetKey,
        ),
    )

    for rank, element, expected_type in candidate_cases:
        assert isinstance(stable_key_candidates(element)[rank], expected_type)


def test_stable_key_prefers_direct_child_id_over_template_ids():
    element = observation(
        """
        <templateId root="template-a"/>
        <id root="id-a" extension="1"/>
        """
    )

    assert stable_key(element) == DirectChildIdElementSetKey(
        root_extensions=(RootExtension(root="id-a", extension="1"),),
    )


def test_stable_key_uses_order_insensitive_direct_id_children_without_mixing_attrs():
    first = observation(
        """
        <id root="id-b" extension="2"/>
        <id root="id-a"/>
        <id extension="missing-root"/>
        """
    )
    second = observation(
        """
        <id root="id-a"/>
        <id root="id-b" extension="2"/>
        """
    )

    assert stable_key(first) == stable_key(second)
    assert stable_key(first) == DirectChildIdElementSetKey(
        root_extensions=(
            RootExtension(root="id-a"),
            RootExtension(root="id-b", extension="2"),
        ),
    )


def test_stable_key_uses_template_id_root_extensions_from_nested_sections():
    component = elem(
        f"""
        <component xmlns="{HL7_NS}">
          <section>
            <templateId root="2" extension="b"/>
            <templateId root="1"/>
          </section>
        </component>
        """
    )

    assert stable_key(component) == NestedSectionTemplateIdElementSetKey(
        root_extensions=(
            RootExtension(root="1"),
            RootExtension(root="2", extension="b"),
        ),
    )


def test_nested_section_template_keys_are_order_insensitive():
    first = elem(
        f"""
        <component xmlns="{HL7_NS}">
          <section><templateId root="b"/></section>
          <section><templateId root="a"/></section>
        </component>
        """
    )
    second = elem(
        f"""
        <component xmlns="{HL7_NS}">
          <section><templateId root="a"/></section>
          <section><templateId root="b"/></section>
        </component>
        """
    )

    assert stable_key(first) == stable_key(second)
    assert stable_key(first) == NestedSectionTemplateIdElementSetKey(
        root_extensions=(
            RootExtension(root="a"),
            RootExtension(root="b"),
        ),
    )


def test_too_many_nested_section_template_keys_do_not_create_partial_key():
    sections = "\n".join(
        f"""<section><templateId root="template-{index}"/></section>"""
        for index in range(13)
    )
    component = elem(
        f"""
        <component xmlns="{HL7_NS}">
          {sections}
        </component>
        """
    )

    assert stable_key(component) is None


def test_nested_statement_id_beats_nested_statement_template_ids():
    entry = elem(
        f"""
        <entry xmlns="{HL7_NS}">
          <observation classCode="OBS" moodCode="EVN">
            <templateId root="template-a"/>
            <id root="statement-id" extension="1"/>
          </observation>
        </entry>
        """
    )

    assert stable_key(entry) == NestedClinicalStatementIdElementSetKey(
        root_extensions=(RootExtension(root="statement-id", extension="1"),),
    )


def test_nested_statement_direct_id_attribute_beats_nested_statement_child_id():
    entry = elem(
        f"""
        <entry xmlns="{HL7_NS}">
          <observation ID="statement-attribute-id">
            <id root="statement-child-id" extension="1"/>
          </observation>
        </entry>
        """
    )

    assert stable_key(entry) == NestedClinicalStatementIdAttributeKey(
        name="ID",
        value="statement-attribute-id",
    )


def test_nested_statement_template_id_used_when_no_identifier_attribute_or_code_exists():
    entry = elem(
        f"""
        <entry xmlns="{HL7_NS}">
          <observation classCode="OBS" moodCode="EVN">
            <templateId root="statement-template"/>
          </observation>
        </entry>
        """
    )

    assert stable_key(entry) == NestedClinicalStatementTemplateIdElementSetKey(
        root_extensions=(RootExtension(root="statement-template"),),
    )


def test_nested_section_id_beats_nested_section_template_ids():
    component = elem(
        f"""
        <component xmlns="{HL7_NS}">
          <section>
            <templateId root="template-a"/>
            <id root="section-id" extension="1"/>
          </section>
        </component>
        """
    )

    assert stable_key(component) == NestedSectionIdElementSetKey(
        root_extensions=(RootExtension(root="section-id", extension="1"),),
    )


def test_nested_section_root_extensions_are_order_insensitive():
    first = elem(
        f"""
        <component xmlns="{HL7_NS}">
          <section><id root="b"/></section>
          <section><id root="a"/></section>
        </component>
        """
    )
    second = elem(
        f"""
        <component xmlns="{HL7_NS}">
          <section><id root="a"/></section>
          <section><id root="b"/></section>
        </component>
        """
    )

    assert stable_key(first) == stable_key(second)
    assert stable_key(first) == NestedSectionIdElementSetKey(
        root_extensions=(
            RootExtension(root="a"),
            RootExtension(root="b"),
        ),
    )


def test_too_many_nested_section_root_extensions_do_not_create_partial_key():
    sections = "\n".join(
        f"""<section><id root="section-{index}"/></section>""" for index in range(13)
    )
    component = elem(
        f"""
        <component xmlns="{HL7_NS}">
          {sections}
        </component>
        """
    )

    assert stable_key(component) is None


def test_direct_code_key_requires_code_system():
    code_with_system = elem(
        f"""<code xmlns="{HL7_NS}" code="123" codeSystem="test-system"/>"""
    )
    code_without_system = elem(f"""<code xmlns="{HL7_NS}" code="123"/>""")

    assert stable_key(code_with_system) == CodeKey(
        code="123",
        code_system="test-system",
    )
    assert stable_key(code_without_system) is None


def test_direct_code_key_only_applies_to_code_elements():
    coded_value_element = elem(
        f"""
        <administrativeGenderCode xmlns="{HL7_NS}"
                                  code="M"
                                  codeSystem="2.16.840.1.113883.5.1"/>
        """
    )

    assert stable_key(coded_value_element) is None


def test_stable_key_uses_order_insensitive_direct_child_code_elements():
    first = observation(
        """
        <code code="b" codeSystem="test-system"/>
        <code code="a" codeSystem="test-system"/>
        <code code="missing-system"/>
        """
    )
    second = observation(
        """
        <code code="a" codeSystem="test-system"/>
        <code code="b" codeSystem="test-system"/>
        """
    )

    assert stable_key(first) == stable_key(second)
    assert stable_key(first) == DirectChildCodeElementSetKey(
        code_elements=(
            CodeElement(code="a", code_system="test-system"),
            CodeElement(code="b", code_system="test-system"),
        ),
    )


def test_direct_child_id_beats_direct_child_code():
    statement = observation(
        """
        <code code="statement-kind" codeSystem="test-system"/>
        <id root="statement-id" extension="1"/>
        """
    )

    assert stable_key(statement) == DirectChildIdElementSetKey(
        root_extensions=(RootExtension(root="statement-id", extension="1"),),
    )


def test_nested_statement_id_beats_direct_child_code():
    entry = elem(
        f"""
        <entry xmlns="{HL7_NS}">
          <code code="entry-kind" codeSystem="test-system"/>
          <observation classCode="OBS" moodCode="EVN">
            <id root="statement-id" extension="1"/>
          </observation>
        </entry>
        """
    )

    assert stable_key(entry) == NestedClinicalStatementIdElementSetKey(
        root_extensions=(RootExtension(root="statement-id", extension="1"),),
    )


def test_stable_key_uses_nested_statement_child_code():
    entry = elem(
        f"""
        <entry xmlns="{HL7_NS}">
          <observation classCode="OBS" moodCode="EVN">
            <code code="statement-kind" codeSystem="test-system"/>
          </observation>
        </entry>
        """
    )

    assert stable_key(entry) == NestedClinicalStatementCodeElementSetKey(
        code_elements=(CodeElement(code="statement-kind", code_system="test-system"),),
    )


def test_direct_child_code_beats_template_ids():
    statement = observation(
        """
        <templateId root="template-a"/>
        <code code="statement-kind" codeSystem="test-system"/>
        """
    )

    assert stable_key(statement) == DirectChildCodeElementSetKey(
        code_elements=(CodeElement(code="statement-kind", code_system="test-system"),),
    )


def test_coded_statement_attributes_do_not_outrank_direct_child_id():
    statement = elem(
        f"""
        <observation xmlns="{HL7_NS}"
                     classCode="OBS"
                     moodCode="EVN"
                     code="not-a-statement-key"
                     codeSystem="test-system">
          <id root="statement-id" extension="1"/>
        </observation>
        """
    )

    assert stable_key(statement) == DirectChildIdElementSetKey(
        root_extensions=(RootExtension(root="statement-id", extension="1"),),
    )


def test_direct_root_extension_key_uses_root_extension_fields():
    id_element = elem(
        f"""<id xmlns="{HL7_NS}" root="document-id-root" extension="document-id-ext"/>"""
    )
    set_id_element = elem(f"""<setId xmlns="{HL7_NS}" root="set-id-root"/>""")

    assert stable_key(id_element) == RootExtensionKey(
        root="document-id-root",
        extension="document-id-ext",
    )
    assert stable_key(set_id_element) == RootExtensionKey(
        root="set-id-root",
    )


def test_direct_root_extension_key_only_applies_to_cda_tags():
    non_cda_id_element = elem(
        """<custom:id xmlns:custom="urn:example"
                      root="custom-id-root"
                      extension="custom-id-ext"/>"""
    )

    assert stable_key(non_cda_id_element) is None


def test_unrelated_descendant_id_is_not_stable_key():
    wrapper = elem(
        f"""
        <wrapper xmlns="{HL7_NS}">
          <unrelated>
            <id root="too-deep" extension="1"/>
          </unrelated>
        </wrapper>
        """
    )

    assert stable_key(wrapper) is None


def test_stable_key_does_not_use_multi_entry_container_statement_key():
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

    assert stable_key(section) is None


def test_stable_key_does_not_use_wrapper_with_multiple_direct_statements():
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

    assert stable_key(entry) is None


def test_stable_key_uses_organizer_itself_for_clinical_statement_key_derivation():
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

    assert stable_key(organizer) == DirectChildIdElementSetKey(
        root_extensions=(RootExtension(root="organizer-id", extension="1"),),
    )
