import pytest
from core import xml_utils
from core.constants import HL7_NS, SDTC_NS, XSI_NS, XSI_TYPE_ATTR
from helpers import assert_xml_equal, elem, find_one

CDA_DOCUMENT_XML = f"""
<ClinicalDocument
    xmlns="{HL7_NS}"
    xmlns:cda="{HL7_NS}"
    xmlns:sdtc="{SDTC_NS}"
    xmlns:xsi="{XSI_NS}"
    xmlns:unused="urn:example:unused">
  <id root="2.16.840.1.113883.19.5" extension="DOC-1"/>
  <component>
    <structuredBody>
      <component>
        <section classCode="DOCSECT">
          <templateId root="2.16.840.1.113883.10.20.15.2.1"/>
          <id root="2.16.840.1.113883.19.5" extension="SECTION-1"/>
          <code code="55751-2" codeSystem="2.16.840.1.113883.6.1"/>
          <text>
            <paragraph>The patient presented with
              <content styleCode="Bold">fever</content>
              and chills.
            </paragraph>
          </text>
          <entry typeCode="DRIV">
            <observation classCode="OBS" moodCode="EVN">
              <templateId
                  root="2.16.840.1.113883.10.20.15.2.3"
                  extension="2024-05-01"/>
              <id root="2.16.840.1.113883.19.5" extension="OBS-1"/>
              <code code="ASSERTION" codeSystem="2.16.840.1.113883.5.4"/>
              <value
                  xsi:type="cda:CD"
                  code="840539006"
                  codeSystem="2.16.840.1.113883.6.96"
                  sdtc:valueSet="2.16.840.1.113883.example"/>
            </observation>
          </entry>
        </section>
      </component>
    </structuredBody>
  </component>
</ClinicalDocument>
"""


def cda_document():
    return elem(CDA_DOCUMENT_XML)


def test_normalize_text_collapses_whitespace():
    raw_text = """
        The patient
          presented with
        fever.
    """

    assert xml_utils.normalize_text(raw_text) == "The patient presented with fever."


def test_localname_returns_tag_without_namespace():
    observation = find_one(cda_document(), ".//hl7:observation[hl7:value]")

    assert xml_utils.localname(observation) == "observation"


def test_fingerprint_ignores_child_order_for_business_equivalent_subtrees():
    first = elem(
        f"""
        <organizer xmlns="{HL7_NS}" classCode="BATTERY" moodCode="EVN">
          <component><observation><code code="A"/></observation></component>
          <component><observation><code code="B"/></observation></component>
        </organizer>
        """
    )
    second = elem(
        f"""
        <organizer xmlns="{HL7_NS}" moodCode="EVN" classCode="BATTERY">
          <component><observation><code code="B"/></observation></component>
          <component><observation><code code="A"/></observation></component>
        </organizer>
        """
    )

    assert xml_utils.fingerprint(first) == xml_utils.fingerprint(second)


def test_fingerprint_detects_mixed_content_tail_changes():
    before = elem(
        f"""
        <paragraph xmlns="{HL7_NS}">
          The patient presented with <content styleCode="Bold">fever</content> and chills.
        </paragraph>
        """
    )
    after = elem(
        f"""
        <paragraph xmlns="{HL7_NS}">
          The patient presented with <content styleCode="Bold">fever</content> and cough.
        </paragraph>
        """
    )

    assert xml_utils.fingerprint(before) != xml_utils.fingerprint(after)


def test_xpath_first_attribute_value_returns_first_match():
    section = find_one(cda_document(), ".//hl7:section")

    assert (
        xml_utils._xpath_first_attribute_value(  # noqa: SLF001
            section,
            "./hl7:templateId/@root",
        )
        == "2.16.840.1.113883.10.20.15.2.1"
    )


def test_xpath_first_attribute_value_returns_none_for_missing_attribute():
    section = find_one(cda_document(), ".//hl7:section")

    assert (
        xml_utils._xpath_first_attribute_value(  # noqa: SLF001
            section,
            "./hl7:templateId/@extension",
        )
        is None
    )


def test_xpath_first_attribute_value_rejects_non_attribute_results():
    section = find_one(cda_document(), ".//hl7:section")

    with pytest.raises(TypeError):
        xml_utils._xpath_first_attribute_value(  # noqa: SLF001
            section,
            "./hl7:id",
        )


def test_xpath_first_element_returns_first_match():
    section = find_one(cda_document(), ".//hl7:section")

    first_id = xml_utils._xpath_first_element(section, "./hl7:id")  # noqa: SLF001

    assert first_id is not None
    assert first_id.get("extension") == "SECTION-1"


def test_xpath_first_element_returns_none_for_missing_element():
    section = find_one(cda_document(), ".//hl7:section")

    assert xml_utils._xpath_first_element(section, "./hl7:author") is None  # noqa: SLF001


def test_xpath_first_element_rejects_non_element_results():
    section = find_one(cda_document(), ".//hl7:section")

    with pytest.raises(TypeError):
        xml_utils._xpath_first_element(section, "./hl7:id/@root")  # noqa: SLF001


def test_collect_subtree_attribute_values_reads_attrs_from_matched_nodes_and_respects_limit():
    section = find_one(cda_document(), ".//hl7:section")

    template_roots = xml_utils._collect_subtree_attribute_values(  # noqa: SLF001
        section,
        ".//hl7:templateId",
        "root",
        limit=2,
    )

    assert template_roots == [
        "2.16.840.1.113883.10.20.15.2.1",
        "2.16.840.1.113883.10.20.15.2.3",
    ]


def test_collect_subtree_attribute_values_skips_nodes_missing_requested_attribute():
    section = find_one(cda_document(), ".//hl7:section")

    template_extensions = xml_utils._collect_subtree_attribute_values(  # noqa: SLF001
        section,
        ".//hl7:templateId",
        "extension",
        limit=8,
    )

    assert template_extensions == ["2024-05-01"]


def test_collect_subtree_attribute_values_returns_empty_list_when_limit_is_not_positive():
    section = find_one(cda_document(), ".//hl7:section")

    assert (
        xml_utils._collect_subtree_attribute_values(  # noqa: SLF001
            section,
            ".//hl7:templateId",
            "root",
            limit=0,
        )
        == []
    )


def test_complete_attribute_pair_returns_pair_only_when_both_values_are_present():
    complete_node = elem("""<id root="root-a" extension="extension-a"/>""")
    incomplete_node = elem("""<id root="root-a"/>""")

    assert xml_utils._complete_attribute_pair(  # noqa: SLF001
        complete_node,
        "root",
        "extension",
    ) == ("root-a", "extension-a")
    assert (
        xml_utils._complete_attribute_pair(  # noqa: SLF001
            incomplete_node,
            "root",
            "extension",
        )
        is None
    )


def test_complete_attribute_pair_returns_none_for_missing_node():
    assert xml_utils._complete_attribute_pair(None, "root", "extension") is None  # noqa: SLF001


def test_collect_standalone_namespace_requirements_finds_used_namespaces_and_qname_prefixes():
    observation = find_one(cda_document(), ".//hl7:observation[hl7:value]")

    used_namespace_uris, required_prefix_bindings = (
        xml_utils._collect_standalone_namespace_requirements(observation)  # noqa: SLF001
    )

    assert HL7_NS in used_namespace_uris
    assert XSI_NS in used_namespace_uris
    assert SDTC_NS in used_namespace_uris
    assert required_prefix_bindings["cda"] == HL7_NS
    assert "unused" not in required_prefix_bindings


def test_build_namespace_map_preserves_qname_prefix_even_when_it_matches_default_namespace():
    observation = find_one(cda_document(), ".//hl7:observation[hl7:value]")

    namespace_map = xml_utils._build_standalone_xml_snippet_namespace_map(  # noqa: SLF001
        observation,
    )

    assert namespace_map[None] == HL7_NS
    assert namespace_map["cda"] == HL7_NS
    assert namespace_map["xsi"] == XSI_NS
    assert namespace_map["sdtc"] == SDTC_NS
    assert "unused" not in namespace_map


def test_build_namespace_map_skips_same_uri_alias_when_no_qname_value_needs_it():
    root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}" xmlns:cda="{HL7_NS}" xmlns:xsi="{XSI_NS}">
          <component>
            <observation classCode="OBS" moodCode="EVN">
              <code code="ASSERTION"/>
            </observation>
          </component>
        </ClinicalDocument>
        """
    )
    observation = find_one(root, ".//hl7:observation")

    namespace_map = xml_utils._build_standalone_xml_snippet_namespace_map(  # noqa: SLF001
        observation,
    )

    assert namespace_map == {None: HL7_NS}


def test_build_standalone_xml_string_outputs_parseable_namespace_complete_snippet():
    observation = find_one(cda_document(), ".//hl7:observation[hl7:value]")

    xml_text = xml_utils.build_standalone_xml_string(observation)
    standalone_observation = elem(xml_text)
    value = find_one(standalone_observation, "./hl7:value")

    assert standalone_observation.nsmap[None] == HL7_NS
    assert standalone_observation.nsmap["cda"] == HL7_NS
    assert standalone_observation.nsmap["xsi"] == XSI_NS
    assert standalone_observation.nsmap["sdtc"] == SDTC_NS
    assert "unused" not in standalone_observation.nsmap
    assert value.get(XSI_TYPE_ATTR) == "cda:CD"
    assert value.get(f"{{{SDTC_NS}}}valueSet") == "2.16.840.1.113883.example"
    assert_xml_equal(
        xml_text,
        f"""
        <observation
            xmlns="{HL7_NS}"
            xmlns:cda="{HL7_NS}"
            xmlns:sdtc="{SDTC_NS}"
            xmlns:xsi="{XSI_NS}"
            classCode="OBS"
            moodCode="EVN">
          <templateId
              extension="2024-05-01"
              root="2.16.840.1.113883.10.20.15.2.3"/>
          <id extension="OBS-1" root="2.16.840.1.113883.19.5"/>
          <code code="ASSERTION" codeSystem="2.16.840.1.113883.5.4"/>
          <value
              code="840539006"
              codeSystem="2.16.840.1.113883.6.96"
              sdtc:valueSet="2.16.840.1.113883.example"
              xsi:type="cda:CD"/>
        </observation>
        """,
    )


def test_build_standalone_xml_string_preserves_child_tail_but_excludes_root_tail():
    root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <section>
              <text>
                <paragraph>The patient presented with
                  <content styleCode="Bold">fever</content>
                  and chills.
                </paragraph>
                Text outside the paragraph.
              </text>
            </section>
          </component>
        </ClinicalDocument>
        """
    )
    paragraph = find_one(root, ".//hl7:paragraph")

    xml_text = xml_utils.build_standalone_xml_string(paragraph)

    assert "and chills" in xml_text
    assert "Text outside the paragraph" not in xml_text


def test_descendant_local_prefix_is_hoisted_when_snippet_root_does_not_bind_that_prefix():
    root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}" xmlns:xsi="{XSI_NS}">
          <component>
            <section>
              <entry>
                <observation classCode="OBS" moodCode="EVN">
                  <value xmlns:cda="{HL7_NS}" xsi:type="cda:CD"/>
                </observation>
              </entry>
            </section>
          </component>
        </ClinicalDocument>
        """
    )
    section = find_one(root, ".//hl7:section")

    xml_text = xml_utils.build_standalone_xml_string(section)
    standalone_section = elem(xml_text)
    value = find_one(standalone_section, ".//hl7:value")

    assert standalone_section.nsmap["cda"] == HL7_NS
    assert value.get(XSI_TYPE_ATTR) == "cda:CD"


def test_descendant_local_prefix_rebinding_stays_local_when_root_binds_same_prefix_differently():
    root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}" xmlns:a="urn:example:type-one" xmlns:xsi="{XSI_NS}">
          <component>
            <section>
              <entry>
                <observation classCode="OBS" moodCode="EVN">
                  <value xsi:type="a:TypeOne"/>
                </observation>
              </entry>
              <entry>
                <organizer classCode="BATTERY" moodCode="EVN" xmlns:a="urn:example:type-two">
                  <component>
                    <observation classCode="OBS" moodCode="EVN">
                      <value xsi:type="a:TypeTwo"/>
                    </observation>
                  </component>
                </organizer>
              </entry>
            </section>
          </component>
        </ClinicalDocument>
        """
    )
    section = find_one(root, ".//hl7:section")

    xml_text = xml_utils.build_standalone_xml_string(section)
    standalone_section = elem(xml_text)
    values = standalone_section.xpath(".//hl7:value", namespaces={"hl7": HL7_NS})

    assert standalone_section.nsmap["a"] == "urn:example:type-one"
    assert values[0].get(XSI_TYPE_ATTR) == "a:TypeOne"
    assert values[1].get(XSI_TYPE_ATTR) == "a:TypeTwo"
    assert values[1].nsmap["a"] == "urn:example:type-two"


def test_build_standalone_xml_string_keeps_conflicting_descendant_prefix_binding_local():
    root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}" xmlns:xsi="{XSI_NS}">
          <component>
            <section>
              <entry>
                <observation classCode="OBS" moodCode="EVN">
                  <value xmlns:lab="urn:example:type-one" xsi:type="lab:TypeOne"/>
                </observation>
              </entry>
              <entry>
                <observation classCode="OBS" moodCode="EVN">
                  <value xmlns:lab="urn:example:type-two" xsi:type="lab:TypeTwo"/>
                </observation>
              </entry>
            </section>
          </component>
        </ClinicalDocument>
        """
    )
    section = find_one(root, ".//hl7:section")

    xml_text = xml_utils.build_standalone_xml_string(section)
    standalone_section = elem(xml_text)
    values = standalone_section.xpath(".//hl7:value", namespaces={"hl7": HL7_NS})

    assert standalone_section.nsmap["lab"] == "urn:example:type-one"
    assert values[0].get(XSI_TYPE_ATTR) == "lab:TypeOne"
    assert values[1].get(XSI_TYPE_ATTR) == "lab:TypeTwo"
    assert values[1].nsmap["lab"] == "urn:example:type-two"


def test_parentless_element_is_serialized_without_rebuilding_namespace_map():
    root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}" xmlns:xsi="{XSI_NS}">
          <id root="2.16.840.1.113883.19.5" extension="DOC-1"/>
        </ClinicalDocument>
        """
    )

    xml_text = xml_utils.build_standalone_xml_string(root)
    round_tripped_root = elem(xml_text)

    assert round_tripped_root.tag == f"{{{HL7_NS}}}ClinicalDocument"
    assert round_tripped_root.nsmap[None] == HL7_NS
    assert_xml_equal(
        xml_text,
        f"""
        <ClinicalDocument xmlns="{HL7_NS}" xmlns:xsi="{XSI_NS}">
          <id root="2.16.840.1.113883.19.5" extension="DOC-1"/>
        </ClinicalDocument>
        """,
    )
