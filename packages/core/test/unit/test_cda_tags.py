from core.cda_tags import (
    CLINICAL_DOCUMENT_TAG,
    CODE_TAG,
    EFFECTIVE_TIME_TAG,
    ID_TAG,
    OBSERVATION_TAG,
    SECTION_TAG,
    SET_ID_TAG,
    TEMPLATE_ID_TAG,
)
from core.xml_utils import hl7_clark_tag


def test_cda_tag_constants_use_hl7_clark_notation():
    assert CLINICAL_DOCUMENT_TAG == hl7_clark_tag("ClinicalDocument")
    assert SET_ID_TAG == hl7_clark_tag("setId")
    assert SECTION_TAG == hl7_clark_tag("section")
    assert OBSERVATION_TAG == hl7_clark_tag("observation")
    assert ID_TAG == hl7_clark_tag("id")
    assert TEMPLATE_ID_TAG == hl7_clark_tag("templateId")
    assert CODE_TAG == hl7_clark_tag("code")
    assert EFFECTIVE_TIME_TAG == hl7_clark_tag("effectiveTime")
