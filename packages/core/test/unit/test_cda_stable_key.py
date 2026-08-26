import pytest
from core.cda.clinical_statement import CDA_CLINICAL_STATEMENT_LOCAL_NAMES
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
    highest_ranked_stable_key,
    stable_key_candidates,
)
from helpers import HL7_NS, elem, observation


@pytest.mark.parametrize(
    ("rank_name", "expected_rank"),
    [
        ("ID_ATTRIBUTE_RANK", 1),
        ("ROOT_EXTENSION_RANK", 2),
        ("CODE_RANK", 3),
        ("DIRECT_CHILD_ID_RANK", 4),
        ("CLINICAL_STATEMENT_ID_ATTRIBUTE_RANK", 5),
        ("CLINICAL_STATEMENT_ID_RANK", 6),
        ("DIRECT_CHILD_CODE_RANK", 7),
        ("CLINICAL_STATEMENT_CODE_RANK", 8),
        ("SECTION_ID_RANK", 9),
        ("DIRECT_CHILD_TEMPLATE_ID_RANK", 10),
        ("SECTION_TEMPLATE_ID_RANK", 11),
        ("CLINICAL_STATEMENT_TEMPLATE_ID_RANK", 12),
    ],
)
def test_stable_key_rank_names_have_expected_values(
    rank_name,
    expected_rank,
):
    assert getattr(STABLE_KEY_RANKS, rank_name) == expected_rank


def test_stable_key_candidates_has_entry_for_every_rank_for_element():
    element = observation('<id root="id-root"/><templateId root="template-root"/>')

    candidates = stable_key_candidates(element)

    assert tuple(candidates) == tuple(STABLE_KEY_RANKS)
    assert candidates[STABLE_KEY_RANKS.ID_ATTRIBUTE_RANK] is None
    assert candidates[STABLE_KEY_RANKS.DIRECT_CHILD_ID_RANK] is not None
    assert candidates[STABLE_KEY_RANKS.DIRECT_CHILD_TEMPLATE_ID_RANK] is not None


@pytest.mark.parametrize(
    ("stable_key_rank", "xml", "expected_candidate"),
    [
        pytest.param(
            STABLE_KEY_RANKS.ID_ATTRIBUTE_RANK,
            f'<observation xmlns="{HL7_NS}" ID="element-id"/>',
            DirectIdAttributeKey(name="ID", value="element-id"),
        ),
        pytest.param(
            STABLE_KEY_RANKS.ROOT_EXTENSION_RANK,
            f'<id xmlns="{HL7_NS}" root="root" extension="extension"/>',
            RootExtensionKey(root="root", extension="extension"),
        ),
        pytest.param(
            STABLE_KEY_RANKS.CODE_RANK,
            f'<code xmlns="{HL7_NS}" code="code" codeSystem="system"/>',
            CodeKey(code="code", code_system="system"),
        ),
        pytest.param(
            STABLE_KEY_RANKS.DIRECT_CHILD_ID_RANK,
            f"""
            <observation xmlns="{HL7_NS}">
              <id root="child-id-a" extension="child-extension-a"/>
              <id root="child-id-b" extension="child-extension-b"/>
            </observation>
            """,
            DirectChildIdElementSetKey(
                root_extensions=(
                    RootExtension(
                        root="child-id-a",
                        extension="child-extension-a",
                    ),
                    RootExtension(
                        root="child-id-b",
                        extension="child-extension-b",
                    ),
                ),
            ),
        ),
        pytest.param(
            STABLE_KEY_RANKS.CLINICAL_STATEMENT_ID_ATTRIBUTE_RANK,
            f'<entry xmlns="{HL7_NS}"><observation ID="statement-id"/></entry>',
            NestedClinicalStatementIdAttributeKey(
                name="ID",
                value="statement-id",
            ),
        ),
        pytest.param(
            STABLE_KEY_RANKS.CLINICAL_STATEMENT_ID_RANK,
            f"""
            <entry xmlns="{HL7_NS}">
              <observation>
                <id root="statement-id-a" extension="statement-extension-a"/>
                <id root="statement-id-b" extension="statement-extension-b"/>
              </observation>
            </entry>
            """,
            NestedClinicalStatementIdElementSetKey(
                root_extensions=(
                    RootExtension(
                        root="statement-id-a",
                        extension="statement-extension-a",
                    ),
                    RootExtension(
                        root="statement-id-b",
                        extension="statement-extension-b",
                    ),
                ),
            ),
        ),
        pytest.param(
            STABLE_KEY_RANKS.DIRECT_CHILD_CODE_RANK,
            f"""
            <observation xmlns="{HL7_NS}">
              <code code="child-code-a" codeSystem="system"/>
              <code code="child-code-b" codeSystem="system"/>
            </observation>
            """,
            DirectChildCodeElementSetKey(
                code_elements=(
                    CodeElement(code="child-code-a", code_system="system"),
                    CodeElement(code="child-code-b", code_system="system"),
                ),
            ),
        ),
        pytest.param(
            STABLE_KEY_RANKS.CLINICAL_STATEMENT_CODE_RANK,
            f"""
            <entry xmlns="{HL7_NS}">
              <observation>
                <code code="statement-code-a" codeSystem="system"/>
                <code code="statement-code-b" codeSystem="system"/>
              </observation>
            </entry>
            """,
            NestedClinicalStatementCodeElementSetKey(
                code_elements=(
                    CodeElement(code="statement-code-a", code_system="system"),
                    CodeElement(code="statement-code-b", code_system="system"),
                ),
            ),
        ),
        pytest.param(
            STABLE_KEY_RANKS.SECTION_ID_RANK,
            f"""
            <component xmlns="{HL7_NS}">
              <section>
                <id root="section-id-a" extension="section-extension-a"/>
                <section>
                  <id root="section-id-b" extension="section-extension-b"/>
                </section>
              </section>
            </component>
            """,
            NestedSectionIdElementSetKey(
                root_extensions=(
                    RootExtension(
                        root="section-id-a",
                        extension="section-extension-a",
                    ),
                    RootExtension(
                        root="section-id-b",
                        extension="section-extension-b",
                    ),
                ),
            ),
        ),
        pytest.param(
            STABLE_KEY_RANKS.DIRECT_CHILD_TEMPLATE_ID_RANK,
            f"""
            <observation xmlns="{HL7_NS}">
              <templateId root="child-template-a" extension="child-template-extension-a"/>
              <templateId root="child-template-b" extension="child-template-extension-b"/>
            </observation>
            """,
            DirectChildTemplateIdElementSetKey(
                root_extensions=(
                    RootExtension(
                        root="child-template-a",
                        extension="child-template-extension-a",
                    ),
                    RootExtension(
                        root="child-template-b",
                        extension="child-template-extension-b",
                    ),
                ),
            ),
        ),
        pytest.param(
            STABLE_KEY_RANKS.SECTION_TEMPLATE_ID_RANK,
            f"""
            <component xmlns="{HL7_NS}">
              <section>
                <templateId root="section-template-a" extension="section-template-extension-a"/>
                <section>
                  <templateId root="section-template-b" extension="section-template-extension-b"/>
                </section>
              </section>
            </component>
            """,
            NestedSectionTemplateIdElementSetKey(
                root_extensions=(
                    RootExtension(
                        root="section-template-a",
                        extension="section-template-extension-a",
                    ),
                    RootExtension(
                        root="section-template-b",
                        extension="section-template-extension-b",
                    ),
                ),
            ),
        ),
        pytest.param(
            STABLE_KEY_RANKS.CLINICAL_STATEMENT_TEMPLATE_ID_RANK,
            f"""
            <entry xmlns="{HL7_NS}">
              <observation>
                <templateId root="statement-template-a" extension="statement-template-extension-a"/>
                <templateId root="statement-template-b" extension="statement-template-extension-b"/>
              </observation>
            </entry>
            """,
            NestedClinicalStatementTemplateIdElementSetKey(
                root_extensions=(
                    RootExtension(
                        root="statement-template-a",
                        extension="statement-template-extension-a",
                    ),
                    RootExtension(
                        root="statement-template-b",
                        extension="statement-template-extension-b",
                    ),
                ),
            ),
        ),
    ],
)
def test_stable_key_candidates_returns_expected_values(
    stable_key_rank,
    xml,
    expected_candidate,
):
    assert stable_key_candidates(elem(xml))[stable_key_rank] == expected_candidate


@pytest.mark.parametrize(
    ("stable_key_rank", "before_xml", "after_xml", "expected_candidate"),
    [
        pytest.param(
            STABLE_KEY_RANKS.DIRECT_CHILD_ID_RANK,
            f"""
            <observation xmlns="{HL7_NS}">
              <id root="id-b" extension="2"/>
              <id root="id-a" extension="1"/>
            </observation>
            """,
            f"""
            <observation xmlns="{HL7_NS}">
              <id root="id-a" extension="1"/>
              <id root="id-b" extension="2"/>
            </observation>
            """,
            DirectChildIdElementSetKey(
                root_extensions=(
                    RootExtension(root="id-a", extension="1"),
                    RootExtension(root="id-b", extension="2"),
                ),
            ),
            id="direct-child-ids",
        ),
        pytest.param(
            STABLE_KEY_RANKS.DIRECT_CHILD_CODE_RANK,
            f"""
            <observation xmlns="{HL7_NS}">
              <code code="code-b" codeSystem="system"/>
              <code code="code-a" codeSystem="system"/>
            </observation>
            """,
            f"""
            <observation xmlns="{HL7_NS}">
              <code code="code-a" codeSystem="system"/>
              <code code="code-b" codeSystem="system"/>
            </observation>
            """,
            DirectChildCodeElementSetKey(
                code_elements=(
                    CodeElement(code="code-a", code_system="system"),
                    CodeElement(code="code-b", code_system="system"),
                ),
            ),
            id="direct-child-codes",
        ),
        pytest.param(
            STABLE_KEY_RANKS.DIRECT_CHILD_TEMPLATE_ID_RANK,
            f"""
            <observation xmlns="{HL7_NS}">
              <templateId root="template-b" extension="2"/>
              <templateId root="template-a" extension="1"/>
            </observation>
            """,
            f"""
            <observation xmlns="{HL7_NS}">
              <templateId root="template-a" extension="1"/>
              <templateId root="template-b" extension="2"/>
            </observation>
            """,
            DirectChildTemplateIdElementSetKey(
                root_extensions=(
                    RootExtension(root="template-a", extension="1"),
                    RootExtension(root="template-b", extension="2"),
                ),
            ),
            id="direct-child-template-ids",
        ),
        pytest.param(
            STABLE_KEY_RANKS.SECTION_ID_RANK,
            f"""
            <component xmlns="{HL7_NS}">
              <section><id root="section-b" extension="2"/></section>
              <section><id root="section-a" extension="1"/></section>
            </component>
            """,
            f"""
            <component xmlns="{HL7_NS}">
              <section><id root="section-a" extension="1"/></section>
              <section><id root="section-b" extension="2"/></section>
            </component>
            """,
            NestedSectionIdElementSetKey(
                root_extensions=(
                    RootExtension(root="section-a", extension="1"),
                    RootExtension(root="section-b", extension="2"),
                ),
            ),
            id="nested-section-ids",
        ),
        pytest.param(
            STABLE_KEY_RANKS.SECTION_TEMPLATE_ID_RANK,
            f"""
            <component xmlns="{HL7_NS}">
              <section><templateId root="template-b" extension="2"/></section>
              <section><templateId root="template-a" extension="1"/></section>
            </component>
            """,
            f"""
            <component xmlns="{HL7_NS}">
              <section><templateId root="template-a" extension="1"/></section>
              <section><templateId root="template-b" extension="2"/></section>
            </component>
            """,
            NestedSectionTemplateIdElementSetKey(
                root_extensions=(
                    RootExtension(root="template-a", extension="1"),
                    RootExtension(root="template-b", extension="2"),
                ),
            ),
            id="nested-section-template-ids",
        ),
        pytest.param(
            STABLE_KEY_RANKS.CLINICAL_STATEMENT_ID_RANK,
            f"""
            <entry xmlns="{HL7_NS}">
              <observation>
                <id root="statement-b" extension="2"/>
                <id root="statement-a" extension="1"/>
              </observation>
            </entry>
            """,
            f"""
            <entry xmlns="{HL7_NS}">
              <observation>
                <id root="statement-a" extension="1"/>
                <id root="statement-b" extension="2"/>
              </observation>
            </entry>
            """,
            NestedClinicalStatementIdElementSetKey(
                root_extensions=(
                    RootExtension(root="statement-a", extension="1"),
                    RootExtension(root="statement-b", extension="2"),
                ),
            ),
            id="nested-clinical-statement-ids",
        ),
        pytest.param(
            STABLE_KEY_RANKS.CLINICAL_STATEMENT_CODE_RANK,
            f"""
            <entry xmlns="{HL7_NS}">
              <observation>
                <code code="code-b" codeSystem="system"/>
                <code code="code-a" codeSystem="system"/>
              </observation>
            </entry>
            """,
            f"""
            <entry xmlns="{HL7_NS}">
              <observation>
                <code code="code-a" codeSystem="system"/>
                <code code="code-b" codeSystem="system"/>
              </observation>
            </entry>
            """,
            NestedClinicalStatementCodeElementSetKey(
                code_elements=(
                    CodeElement(code="code-a", code_system="system"),
                    CodeElement(code="code-b", code_system="system"),
                ),
            ),
            id="nested-clinical-statement-codes",
        ),
        pytest.param(
            STABLE_KEY_RANKS.CLINICAL_STATEMENT_TEMPLATE_ID_RANK,
            f"""
            <entry xmlns="{HL7_NS}">
              <observation>
                <templateId root="template-b" extension="2"/>
                <templateId root="template-a" extension="1"/>
              </observation>
            </entry>
            """,
            f"""
            <entry xmlns="{HL7_NS}">
              <observation>
                <templateId root="template-a" extension="1"/>
                <templateId root="template-b" extension="2"/>
              </observation>
            </entry>
            """,
            NestedClinicalStatementTemplateIdElementSetKey(
                root_extensions=(
                    RootExtension(root="template-a", extension="1"),
                    RootExtension(root="template-b", extension="2"),
                ),
            ),
            id="nested-clinical-statement-template-ids",
        ),
    ],
)
def test_list_based_stable_key_candidates_are_order_insensitive(
    stable_key_rank,
    before_xml,
    after_xml,
    expected_candidate,
):
    first_candidate = stable_key_candidates(elem(before_xml))[stable_key_rank]
    second_candidate = stable_key_candidates(elem(after_xml))[stable_key_rank]

    assert first_candidate == second_candidate
    assert first_candidate == expected_candidate


def test_stable_key_does_not_use_weak_attributes_as_key():
    element = elem(
        f"""
        <observation xmlns="{HL7_NS}" classCode="OBS" moodCode="EVN"/>
        """
    )

    assert highest_ranked_stable_key(element) is None


def test_highest_ranked_stable_key_prefers_higher_rank_over_lower_rank():
    element = observation(
        """
        <templateId root="template-a"/>
        <id root="id-a" extension="1"/>
        """
    )

    candidates = stable_key_candidates(element)
    expected_id_candidate = DirectChildIdElementSetKey(
        root_extensions=(RootExtension(root="id-a", extension="1"),),
    )
    expected_template_candidate = DirectChildTemplateIdElementSetKey(
        root_extensions=(RootExtension(root="template-a"),),
    )

    assert candidates[STABLE_KEY_RANKS.DIRECT_CHILD_ID_RANK] == expected_id_candidate
    assert (
        candidates[STABLE_KEY_RANKS.DIRECT_CHILD_TEMPLATE_ID_RANK]
        == expected_template_candidate
    )
    assert highest_ranked_stable_key(element) == expected_id_candidate


def test_stable_key_ignores_direct_id_children_without_root():
    statement = observation(
        """
        <id root="id-a"/>
        <id extension="missing-root"/>
        """
    )

    assert highest_ranked_stable_key(statement) == DirectChildIdElementSetKey(
        root_extensions=(RootExtension(root="id-a"),),
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

    assert highest_ranked_stable_key(component) is None


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

    assert highest_ranked_stable_key(component) is None


def test_direct_code_key_requires_code_system():
    code_with_system = elem(
        f"""<code xmlns="{HL7_NS}" code="123" codeSystem="test-system"/>"""
    )
    code_without_system = elem(f"""<code xmlns="{HL7_NS}" code="123"/>""")

    assert highest_ranked_stable_key(code_with_system) == CodeKey(
        code="123",
        code_system="test-system",
    )
    assert highest_ranked_stable_key(code_without_system) is None


def test_direct_code_key_only_applies_to_code_elements():
    coded_value_element = elem(
        f"""
        <administrativeGenderCode xmlns="{HL7_NS}"
                                  code="M"
                                  codeSystem="2.16.840.1.113883.5.1"/>
        """
    )

    assert highest_ranked_stable_key(coded_value_element) is None


def test_tags_having_root_extension_keys_use_root_extension_fields_as_key():
    id_element = elem(
        f"""<id xmlns="{HL7_NS}" root="document-id-root" extension="document-id-ext"/>"""
    )
    set_id_element = elem(f"""<setId xmlns="{HL7_NS}" root="set-id-root"/>""")
    template_id_element = elem(
        f"""<templateId xmlns="{HL7_NS}" root="template-id-root" extension="template-id-ext"/>"""
    )

    assert highest_ranked_stable_key(id_element) == RootExtensionKey(
        root="document-id-root",
        extension="document-id-ext",
    )
    assert highest_ranked_stable_key(set_id_element) == RootExtensionKey(
        root="set-id-root",
    )
    assert highest_ranked_stable_key(template_id_element) == RootExtensionKey(
        root="template-id-root",
        extension="template-id-ext",
    )


def test_direct_root_extension_key_only_applies_to_cda_tags():
    non_cda_id_element = elem(
        """<custom:id xmlns:custom="urn:example"
                      root="custom-id-root"
                      extension="custom-id-ext"/>"""
    )

    assert highest_ranked_stable_key(non_cda_id_element) is None


def test_descendant_id_of_non_clinical_statement_direct_descendant_is_not_highest_ranked_stable_key():
    wrapper = elem(
        f"""
        <wrapper xmlns="{HL7_NS}">
          <unrelated>
            <id root="too-deep" extension="1"/>
          </unrelated>
        </wrapper>
        """
    )

    assert highest_ranked_stable_key(wrapper) is None


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

    assert highest_ranked_stable_key(entry) is None


@pytest.mark.parametrize(
    "clinical_statement_local_name",
    sorted(CDA_CLINICAL_STATEMENT_LOCAL_NAMES),
)
def test_clinical_statement_uses_its_own_child_ids_for_key_derivation(
    clinical_statement_local_name,
):
    clinical_statement = elem(
        f"""
        <{clinical_statement_local_name} xmlns="{HL7_NS}">
          <id root="statement-id"/>
          <component>
            <observation>
              <id root="nested-observation-id"/>
            </observation>
          </component>
        </{clinical_statement_local_name}>
        """
    )

    assert highest_ranked_stable_key(clinical_statement) == (
        DirectChildIdElementSetKey(
            root_extensions=(RootExtension(root="statement-id"),),
        )
    )
