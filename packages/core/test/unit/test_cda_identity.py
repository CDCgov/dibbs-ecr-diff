from core.cda_identity import (
    DIRECT_TEMPLATE_ID_TAG,
    CodeKey,
    ElementSetKeySource,
    IdAttributeKey,
    IdAttributeKeySource,
    IdElementSetKey,
    RootExtension,
    RootExtensionKey,
    TemplateIdElementSetKey,
    _clinical_statement_for_identity,
    _direct_child_root_extensions_for_tag,
    soft_context_key,
    stable_key,
)
from helpers import HL7_NS, elem, observation


def test_direct_child_root_extensions_for_tag_sorts_deduplicates_and_skips_missing_root():
    element = observation(
        """
        <templateId root="2" extension="b"/>
        <templateId root="1"/>
        <templateId root="2" extension="b"/>
        <templateId extension="missing-root"/>
        """
    )

    assert _direct_child_root_extensions_for_tag(
        element,
        DIRECT_TEMPLATE_ID_TAG,
    ) == (
        RootExtension(root="1"),
        RootExtension(root="2", extension="b"),
    )


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
    assert stable_key(first) == TemplateIdElementSetKey(
        source=ElementSetKeySource.DIRECT_CHILD,
        root_extensions=(
            RootExtension(root="1"),
            RootExtension(root="2", extension="b"),
        ),
    )


def test_stable_key_does_not_use_weak_attributes_as_identity():
    element = elem(
        f"""
        <observation xmlns="{HL7_NS}" classCode="OBS" moodCode="EVN"/>
        """
    )

    assert stable_key(element) is None


def test_stable_key_prefers_direct_child_id_over_template_ids():
    element = observation(
        """
        <templateId root="template-a"/>
        <id root="id-a" extension="1"/>
        """
    )

    assert stable_key(element) == IdElementSetKey(
        source=ElementSetKeySource.DIRECT_CHILD,
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
    assert stable_key(first) == IdElementSetKey(
        source=ElementSetKeySource.DIRECT_CHILD,
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

    assert stable_key(component) == TemplateIdElementSetKey(
        source=ElementSetKeySource.NESTED_SECTION,
        root_extensions=(
            RootExtension(root="1"),
            RootExtension(root="2", extension="b"),
        ),
    )


def test_nested_section_template_identities_are_order_insensitive():
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
    assert stable_key(first) == TemplateIdElementSetKey(
        source=ElementSetKeySource.NESTED_SECTION,
        root_extensions=(
            RootExtension(root="a"),
            RootExtension(root="b"),
        ),
    )


def test_too_many_nested_section_template_identities_do_not_create_partial_key():
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

    assert stable_key(entry) == IdElementSetKey(
        source=ElementSetKeySource.NESTED_CLINICAL_STATEMENT,
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

    assert stable_key(entry) == IdAttributeKey(
        source=IdAttributeKeySource.NESTED_CLINICAL_STATEMENT,
        name="ID",
        value="statement-attribute-id",
    )


def test_nested_statement_direct_id_attribute_does_not_use_code_attributes():
    entry = elem(
        f"""
        <entry xmlns="{HL7_NS}">
          <observation code="not-a-direct-statement-identity"
                       codeSystem="test-system">
            <templateId root="statement-template"/>
          </observation>
        </entry>
        """
    )

    assert stable_key(entry) == TemplateIdElementSetKey(
        source=ElementSetKeySource.NESTED_CLINICAL_STATEMENT,
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

    assert stable_key(component) == IdElementSetKey(
        source=ElementSetKeySource.NESTED_SECTION,
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
    assert stable_key(first) == IdElementSetKey(
        source=ElementSetKeySource.NESTED_SECTION,
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


def test_unrelated_descendant_id_is_not_stable_identity():
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
    assert stable_key(organizer) == IdElementSetKey(
        source=ElementSetKeySource.DIRECT_CHILD,
        root_extensions=(RootExtension(root="organizer-id", extension="1"),),
    )


def test_soft_context_key_uses_full_direct_template_id_root_extensions():
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
    different_extension = observation(
        """
        <templateId root="1"/>
        <templateId root="2" extension="c"/>
        """
    )

    assert soft_context_key(first) == soft_context_key(second)
    assert soft_context_key(first) != soft_context_key(different_extension)
