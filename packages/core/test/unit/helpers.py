from textwrap import dedent

import pytest
from core.constants import HL7_NS, NAMESPACES
from lxml import etree

SECTION_LOINC_CODE_CASES = [
    pytest.param(
        f"""
        <section xmlns="{HL7_NS}">
          <code code="10160-0" codeSystem="2.16.840.1.113883.6.1"/>
          <component>
            <section>
              <code code="18776-5" codeSystem="2.16.840.1.113883.6.1"/>
              <entry>
                <observation>
                  <code code="718-7" codeSystem="2.16.840.1.113883.6.1"/>
                  <value ID="target"/>
                </observation>
              </entry>
            </section>
          </component>
        </section>
        """,
        "18776-5",
        id="nearest-nested-section",
    ),
    pytest.param(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <section ID="target">
              <code code="18776-5" codeSystem="2.16.840.1.113883.6.1"/>
            </section>
          </component>
        </ClinicalDocument>
        """,
        "18776-5",
        id="changed-section",
    ),
    pytest.param(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <recordTarget ID="target"/>
        </ClinicalDocument>
        """,
        None,
        id="outside-section",
    ),
    pytest.param(
        f"""
        <section xmlns="{HL7_NS}">
          <code code="365860008" codeSystem="2.16.840.1.113883.6.96"/>
          <observation>
            <code code="718-7" codeSystem="2.16.840.1.113883.6.1"/>
            <value ID="target"/>
          </observation>
        </section>
        """,
        None,
        id="non-loinc-code-system",
    ),
    pytest.param(
        f"""
        <section xmlns="{HL7_NS}">
          <code code="not-a-loinc-code"
                codeSystem="2.16.840.1.113883.6.1"/>
          <value ID="target"/>
        </section>
        """,
        None,
        id="invalid-loinc-code",
    ),
]


def elem(xml: str) -> etree._Element:
    return etree.fromstring(dedent(xml).encode("utf-8"))


def observation(key_children: str, body: str = "") -> etree._Element:
    return elem(
        f"""
        <observation xmlns="{HL7_NS}" classCode="OBS" moodCode="EVN">
          {key_children}
          {body}
        </observation>
        """
    )


def find_one(element: etree._Element, xpath_expression: str) -> etree._Element:
    result = element.xpath(xpath_expression, namespaces=NAMESPACES)
    assert len(result) == 1
    assert isinstance(result[0], etree._Element)
    return result[0]


def assert_xml_equal(actual_xml: str, expected_xml: str) -> None:
    parser = etree.XMLParser(remove_blank_text=True)
    actual = etree.fromstring(actual_xml.encode("utf-8"), parser)
    expected = etree.fromstring(dedent(expected_xml).strip().encode("utf-8"), parser)
    assert etree.tostring(actual, method="c14n") == etree.tostring(
        expected,
        method="c14n",
    )
