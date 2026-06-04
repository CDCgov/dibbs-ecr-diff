from core.paths import stable_xml_path, xpath_with_predicates
from helpers import HL7_NS, elem


def test_paths_include_all_direct_template_id_identities():
    root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <observation classCode="OBS" moodCode="EVN">
              <templateId root="1"/>
              <templateId root="2" extension="b"/>
            </observation>
          </component>
        </ClinicalDocument>
        """
    )
    observation = root.xpath(
        ".//hl7:observation",
        namespaces={"hl7": HL7_NS},
    )[0]

    xml_path = stable_xml_path(observation)
    x_path = xpath_with_predicates(observation)

    assert "observation[templates:root=1|root=2;extension=b]" in xml_path
    assert "hl7:templateId[@root='1' and (not(@extension) or @extension='')]" in x_path
    assert "hl7:templateId[@root='2' and @extension='b']" in x_path


def test_paths_include_direct_id_attribute_identity():
    root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <observation ID="target-observation"/>
          </component>
        </ClinicalDocument>
        """
    )
    observation = root.xpath(
        ".//hl7:observation",
        namespaces={"hl7": HL7_NS},
    )[0]

    xml_path = stable_xml_path(observation)
    x_path = xpath_with_predicates(observation)

    assert "observation[attrs:ID=target-observation]" in xml_path
    assert "hl7:observation[@ID='target-observation']" in x_path


def test_paths_include_direct_code_element_identity():
    root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <code code="55751-2" codeSystem="2.16.840.1.113883.6.1"/>
        </ClinicalDocument>
        """
    )
    code = root.xpath(
        "./hl7:code",
        namespaces={"hl7": HL7_NS},
    )[0]

    xml_path = stable_xml_path(code)
    x_path = xpath_with_predicates(code)

    assert "code[code:code=55751-2;codeSystem=2.16.840.1.113883.6.1]" in xml_path
    assert "hl7:code[@code='55751-2' and @codeSystem='2.16.840.1.113883.6.1']" in x_path
