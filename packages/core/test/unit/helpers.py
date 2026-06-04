from textwrap import dedent

from core.constants import HL7_NAMESPACE, HL7_NS
from lxml import etree


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
    result = element.xpath(xpath_expression, namespaces=HL7_NAMESPACE)
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
