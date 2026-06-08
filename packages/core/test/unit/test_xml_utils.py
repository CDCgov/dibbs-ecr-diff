"""
Tests for core.constants and core.xml_utils.

These tests use small CDA-like XML fragments rather than generic XML so the
business cases stay close to eICR/CDA data
"""

from textwrap import dedent

import pytest
from core import constants, xml_utils
from core.cda_tags import CLINICAL_DOCUMENT_TAG
from lxml import etree

HL7_NS = constants.HL7_NS
SDTC_NS = constants.SDTC_NS
XSI_NS = constants.XSI_NS
NAMESPACES = constants.NAMESPACES


def parse_xml(xml_text: str) -> etree._Element:
    """Parse an XML string into an lxml element."""
    return etree.fromstring(xml_text.encode("utf-8"))


def find_one(element: etree._Element, xpath_expression: str) -> etree._Element:
    """Return exactly one element from a test XPath expression."""
    results = element.xpath(xpath_expression, namespaces=NAMESPACES)
    assert len(results) == 1
    result = results[0]
    assert isinstance(result, etree._Element)
    return result


def canonical_xml(xml_text: str) -> bytes:
    parser = etree.XMLParser(remove_blank_text=True)
    root = etree.fromstring(xml_text.encode("utf-8"), parser=parser)
    return etree.tostring(root, method="c14n")


def assert_xml_equal(actual_xml: str, expected_xml: str) -> None:
    assert canonical_xml(actual_xml) == canonical_xml(expected_xml)


def test_clark_tag_helpers_use_expected_namespaces():
    assert xml_utils.clark_tag(HL7_NS, "id") == xml_utils.hl7_clark_tag("id")
    assert xml_utils.hl7_clark_tag("id") == "{urn:hl7-org:v3}id"
    assert xml_utils.sdtc_clark_tag("valueSet") == "{urn:hl7-org:sdtc}valueSet"
    assert (
        xml_utils.xsi_clark_tag("type")
        == "{http://www.w3.org/2001/XMLSchema-instance}type"
    )


@pytest.fixture
def cda_document() -> etree._Element:
    """A small CDA-like document with inherited namespaces and nested entries."""
    return parse_xml(
        f"""
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
                      <templateId root="2.16.840.1.113883.10.20.15.2.3" extension="2024-05-01"/>
                      <id root="2.16.840.1.113883.19.5" extension="OBS-1"/>
                      <code code="ASSERTION" codeSystem="2.16.840.1.113883.5.4"/>
                      <value xsi:type="cda:CD"
                             code="840539006"
                             codeSystem="2.16.840.1.113883.6.96"
                             sdtc:valueSet="2.16.840.1.113883.example"/>
                    </observation>
                  </entry>
                  <entry typeCode="DRIV">
                    <observation classCode="OBS" moodCode="EVN">
                      <templateId/>
                      <templateId root="2.16.840.1.113883.10.20.15.2.4"/>
                      <id root="2.16.840.1.113883.19.5" extension="OBS-2"/>
                    </observation>
                  </entry>
                </section>
              </component>
            </structuredBody>
          </component>
        </ClinicalDocument>
        """
    )


# ---------------------------------------------------------------------------
# constants.py
# ---------------------------------------------------------------------------


def test_namespace_constants_are_internally_consistent() -> None:
    assert constants.NAMESPACES[constants.HL7_PREFIX] == constants.HL7_NS
    assert constants.NAMESPACES[constants.SDTC_PREFIX] == constants.SDTC_NS
    assert constants.NAMESPACES[constants.XSI_PREFIX] == constants.XSI_NS


# ---------------------------------------------------------------------------
# Text and tag helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        (None, ""),
        ("", ""),
        ("  fever   and\nchills\t", "fever and chills"),
        ("already normalized", "already normalized"),
    ],
)
def test_normalize_text_collapses_whitespace(
    raw_text: str | None, expected: str
) -> None:
    assert xml_utils.normalize_text(raw_text) == expected


def test_localname_returns_tag_without_namespace(cda_document: etree._Element) -> None:
    observation = find_one(cda_document, ".//hl7:observation[hl7:value]")
    assert xml_utils.localname(observation) == "observation"


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------


def test_fingerprint_ignores_child_order_for_business_equivalent_subtrees() -> None:
    first = parse_xml(
        f"""
        <organizer xmlns="{HL7_NS}" classCode="BATTERY" moodCode="EVN">
          <component><observation><code code="A"/></observation></component>
          <component><observation><code code="B"/></observation></component>
        </organizer>
        """
    )
    second = parse_xml(
        f"""
        <organizer xmlns="{HL7_NS}" moodCode="EVN" classCode="BATTERY">
          <component><observation><code code="B"/></observation></component>
          <component><observation><code code="A"/></observation></component>
        </organizer>
        """
    )

    assert xml_utils.fingerprint(first) == xml_utils.fingerprint(second)


def test_fingerprint_detects_mixed_content_tail_changes() -> None:
    before = parse_xml(
        f"""
        <paragraph xmlns="{HL7_NS}">
          The patient presented with <content styleCode="Bold">fever</content> and chills.
        </paragraph>
        """
    )
    after = parse_xml(
        f"""
        <paragraph xmlns="{HL7_NS}">
          The patient presented with <content styleCode="Bold">fever</content> and cough.
        </paragraph>
        """
    )

    assert xml_utils.fingerprint(before) != xml_utils.fingerprint(after)


# ---------------------------------------------------------------------------
# XPath helpers
# ---------------------------------------------------------------------------


def test_xpath_first_attribute_value_returns_first_match(
    cda_document: etree._Element,
) -> None:
    section = find_one(cda_document, ".//hl7:section")

    assert (
        xml_utils._xpath_first_attribute_value(section, "./hl7:templateId/@root")
        == "2.16.840.1.113883.10.20.15.2.1"
    )


def test_xpath_first_attribute_value_returns_none_for_missing_attribute(
    cda_document: etree._Element,
) -> None:
    section = find_one(cda_document, ".//hl7:section")

    assert (
        xml_utils._xpath_first_attribute_value(section, "./hl7:templateId/@extension")
        is None
    )


@pytest.mark.parametrize(
    "xpath_expression",
    [
        "./hl7:id",
        "string(./hl7:id/@root)",
    ],
)
def test_xpath_first_attribute_value_rejects_non_attribute_results(
    cda_document: etree._Element,
    xpath_expression: str,
) -> None:
    section = find_one(cda_document, ".//hl7:section")

    with pytest.raises(TypeError):
        xml_utils._xpath_first_attribute_value(section, xpath_expression)


def test_xpath_first_element_returns_first_match(cda_document: etree._Element) -> None:
    section = find_one(cda_document, ".//hl7:section")

    first_id = xml_utils._xpath_first_element(section, "./hl7:id")

    assert first_id is not None
    assert first_id.get("extension") == "SECTION-1"


def test_xpath_first_element_returns_none_for_missing_element(
    cda_document: etree._Element,
) -> None:
    section = find_one(cda_document, ".//hl7:section")

    assert xml_utils._xpath_first_element(section, "./hl7:author") is None


@pytest.mark.parametrize(
    "xpath_expression",
    [
        "./hl7:id/@root",
        "count(./hl7:id)",
    ],
)
def test_xpath_first_element_rejects_non_element_results(
    cda_document: etree._Element,
    xpath_expression: str,
) -> None:
    section = find_one(cda_document, ".//hl7:section")

    with pytest.raises(TypeError):
        xml_utils._xpath_first_element(section, xpath_expression)


# ---------------------------------------------------------------------------
# Attribute collection helpers
# ---------------------------------------------------------------------------


def test_collect_subtree_attribute_values_reads_attrs_from_matched_nodes_and_respects_limit(
    cda_document: etree._Element,
) -> None:
    section = find_one(cda_document, ".//hl7:section")

    template_roots = xml_utils._collect_subtree_attribute_values(
        section,
        ".//hl7:templateId",
        "root",
        limit=2,
    )

    assert template_roots == [
        "2.16.840.1.113883.10.20.15.2.1",
        "2.16.840.1.113883.10.20.15.2.3",
    ]


def test_collect_subtree_attribute_values_skips_nodes_missing_requested_attribute(
    cda_document: etree._Element,
) -> None:
    section = find_one(cda_document, ".//hl7:section")

    template_extensions = xml_utils._collect_subtree_attribute_values(
        section,
        ".//hl7:templateId",
        "extension",
        limit=8,
    )

    assert template_extensions == ["2024-05-01"]


@pytest.mark.parametrize("limit", [0, -1])
def test_collect_subtree_attribute_values_returns_empty_list_when_limit_is_not_positive(
    cda_document: etree._Element,
    limit: int,
) -> None:
    section = find_one(cda_document, ".//hl7:section")

    assert (
        xml_utils._collect_subtree_attribute_values(
            section,
            ".//hl7:templateId",
            "root",
            limit=limit,
        )
        == []
    )


@pytest.mark.parametrize(
    ("node_xml", "expected"),
    [
        ('<id root="root-1" extension="ext-1"/>', ("root-1", "ext-1")),
        ('<id root="root-1"/>', None),
        ('<id extension="ext-1"/>', None),
    ],
)
def test_complete_attribute_pair_returns_pair_only_when_both_values_are_present(
    node_xml: str,
    expected: tuple[str, str] | None,
) -> None:
    node = parse_xml(node_xml)

    assert xml_utils._complete_attribute_pair(node, "root", "extension") == expected


def test_complete_attribute_pair_returns_none_for_missing_node() -> None:
    assert xml_utils._complete_attribute_pair(None, "root", "extension") is None


# ---------------------------------------------------------------------------
# Standalone namespace collection and serialization
# ---------------------------------------------------------------------------


def test_collect_standalone_namespace_requirements_finds_used_namespaces_and_qname_prefixes(
    cda_document: etree._Element,
) -> None:
    observation = find_one(cda_document, ".//hl7:observation[hl7:value]")

    used_namespace_uris, required_prefix_bindings = (
        xml_utils._collect_standalone_namespace_requirements(observation)
    )

    assert HL7_NS in used_namespace_uris
    assert XSI_NS in used_namespace_uris
    assert SDTC_NS in used_namespace_uris
    assert required_prefix_bindings == {"cda": HL7_NS}
    assert "unused" not in used_namespace_uris


def test_build_namespace_map_preserves_qname_prefix_even_when_it_matches_default_namespace(
    cda_document: etree._Element,
) -> None:
    observation = find_one(cda_document, ".//hl7:observation[hl7:value]")

    namespace_map = xml_utils._build_standalone_xml_snippet_namespace_map(observation)

    assert namespace_map[None] == HL7_NS
    assert namespace_map["cda"] == HL7_NS
    assert namespace_map["xsi"] == XSI_NS
    assert namespace_map["sdtc"] == SDTC_NS
    assert "unused" not in namespace_map


def test_build_namespace_map_skips_same_uri_alias_when_no_qname_value_needs_it() -> (
    None
):
    document = parse_xml(
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
    observation = find_one(document, ".//hl7:observation")

    namespace_map = xml_utils._build_standalone_xml_snippet_namespace_map(observation)

    assert namespace_map == {None: HL7_NS}


def test_build_standalone_xml_string_outputs_parseable_namespace_complete_snippet(
    cda_document: etree._Element,
) -> None:
    observation = find_one(cda_document, ".//hl7:observation[hl7:value]")

    xml_text = xml_utils.build_standalone_xml_string(observation)
    standalone_observation = parse_xml(xml_text)
    value = find_one(standalone_observation, "./hl7:value")

    assert standalone_observation.nsmap[None] == HL7_NS
    assert standalone_observation.nsmap["cda"] == HL7_NS
    assert standalone_observation.nsmap["xsi"] == XSI_NS
    assert standalone_observation.nsmap["sdtc"] == SDTC_NS
    assert "unused" not in standalone_observation.nsmap
    assert value.get(xml_utils.xsi_clark_tag("type")) == "cda:CD"
    assert value.get(xml_utils.sdtc_clark_tag("valueSet")) == (
        "2.16.840.1.113883.example"
    )

    expected_xml = dedent(
        f"""
        <observation
            xmlns="{HL7_NS}"
            xmlns:cda="{HL7_NS}"
            xmlns:sdtc="{SDTC_NS}"
            xmlns:xsi="{XSI_NS}"
            classCode="OBS"
            moodCode="EVN">
          <templateId extension="2024-05-01" root="2.16.840.1.113883.10.20.15.2.3"/>
          <id extension="OBS-1" root="2.16.840.1.113883.19.5"/>
          <code code="ASSERTION" codeSystem="2.16.840.1.113883.5.4"/>
          <value
              code="840539006"
              codeSystem="2.16.840.1.113883.6.96"
              sdtc:valueSet="2.16.840.1.113883.example"
              xsi:type="cda:CD"/>
        </observation>
        """
    ).strip()
    assert_xml_equal(xml_text, expected_xml)


def test_build_standalone_xml_string_preserves_child_tail_but_excludes_root_tail() -> (
    None
):
    document = parse_xml(
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
    paragraph = find_one(document, ".//hl7:paragraph")

    xml_text = xml_utils.build_standalone_xml_string(paragraph)

    assert "and chills" in xml_text
    assert "Text outside the paragraph" not in xml_text


def test_descendant_local_prefix_is_hoisted_when_snippet_root_does_not_bind_that_prefix() -> (
    None
):
    document = parse_xml(
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
    section = find_one(document, ".//hl7:section")

    _, required_prefix_bindings = xml_utils._collect_standalone_namespace_requirements(
        section
    )
    xml_text = xml_utils.build_standalone_xml_string(section)
    standalone_section = parse_xml(xml_text)
    value = find_one(standalone_section, ".//hl7:value")

    assert required_prefix_bindings == {"cda": HL7_NS}
    assert standalone_section.nsmap["cda"] == HL7_NS
    assert value.nsmap["cda"] == HL7_NS
    assert value.get(xml_utils.xsi_clark_tag("type")) == "cda:CD"

    expected_xml = dedent(
        f"""
        <section xmlns="{HL7_NS}" xmlns:cda="{HL7_NS}" xmlns:xsi="{XSI_NS}">
          <entry>
            <observation classCode="OBS" moodCode="EVN">
              <value xsi:type="cda:CD"/>
            </observation>
          </entry>
        </section>
        """
    ).strip()

    assert_xml_equal(xml_text, expected_xml)


def test_descendant_local_prefix_rebinding_stays_local_when_root_binds_same_prefix_differently() -> (
    None
):
    document = parse_xml(
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
    section = find_one(document, ".//hl7:section")

    xml_text = xml_utils.build_standalone_xml_string(section)
    standalone_section = parse_xml(xml_text)
    first_value = find_one(
        standalone_section, "./hl7:entry[1]/hl7:observation/hl7:value"
    )
    second_value = find_one(
        standalone_section,
        "./hl7:entry[2]/hl7:organizer/hl7:component/hl7:observation/hl7:value",
    )

    assert first_value.nsmap["a"] == "urn:example:type-one"
    assert second_value.nsmap["a"] == "urn:example:type-two"
    assert first_value.get(xml_utils.xsi_clark_tag("type")) == "a:TypeOne"
    assert second_value.get(xml_utils.xsi_clark_tag("type")) == "a:TypeTwo"

    expected_xml = dedent(
        f"""
        <section xmlns="{HL7_NS}" xmlns:a="urn:example:type-one" xmlns:xsi="{XSI_NS}">
          <entry>
            <observation classCode="OBS" moodCode="EVN">
              <value xsi:type="a:TypeOne"/>
            </observation>
          </entry>
          <entry>
            <organizer xmlns:a="urn:example:type-two" classCode="BATTERY" moodCode="EVN">
              <component>
                <observation classCode="OBS" moodCode="EVN">
                  <value xsi:type="a:TypeTwo"/>
                </observation>
              </component>
            </organizer>
          </entry>
        </section>
        """
    ).strip()

    assert_xml_equal(xml_text, expected_xml)


def test_build_standalone_xml_string_keeps_conflicting_descendant_prefix_binding_local() -> (
    None
):
    document = parse_xml(
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
    section = find_one(document, ".//hl7:section")

    xml_text = xml_utils.build_standalone_xml_string(section)
    standalone_section = parse_xml(xml_text)

    first_value = find_one(
        standalone_section,
        "./hl7:entry[1]/hl7:observation/hl7:value",
    )
    second_value = find_one(
        standalone_section,
        "./hl7:entry[2]/hl7:observation/hl7:value",
    )

    assert standalone_section.nsmap["lab"] == "urn:example:type-one"

    assert first_value.get(xml_utils.xsi_clark_tag("type")) == "lab:TypeOne"
    assert first_value.nsmap["lab"] == "urn:example:type-one"

    assert second_value.get(xml_utils.xsi_clark_tag("type")) == "lab:TypeTwo"
    assert second_value.nsmap["lab"] == "urn:example:type-two"

    expected_xml = dedent(
        f"""
        <section xmlns="{HL7_NS}" xmlns:lab="urn:example:type-one" xmlns:xsi="{XSI_NS}">
          <entry>
            <observation classCode="OBS" moodCode="EVN">
              <value xsi:type="lab:TypeOne"/>
            </observation>
          </entry>
          <entry>
            <observation classCode="OBS" moodCode="EVN">
              <value xmlns:lab="urn:example:type-two" xsi:type="lab:TypeTwo"/>
            </observation>
          </entry>
        </section>
        """
    ).strip()

    assert_xml_equal(xml_text, expected_xml)


def test_parentless_element_is_serialized_without_rebuilding_namespace_map() -> None:
    initial_xml = f"""
        <ClinicalDocument xmlns="{HL7_NS}" xmlns:xsi="{XSI_NS}">
          <id root="2.16.840.1.113883.19.5" extension="DOC-1"/>
        </ClinicalDocument>
        """
    root = parse_xml(initial_xml)

    xml_text = xml_utils.build_standalone_xml_string(root)
    round_tripped_root = parse_xml(xml_text)
    expected_xml = dedent(initial_xml).strip()

    assert round_tripped_root.tag == CLINICAL_DOCUMENT_TAG
    assert round_tripped_root.nsmap[None] == HL7_NS
    assert_xml_equal(xml_text, expected_xml)
