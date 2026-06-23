"""Common CDA element tags in Clark notation."""

from core.xml_utils import hl7_clark_tag

CLINICAL_DOCUMENT_TAG = hl7_clark_tag("ClinicalDocument")
SET_ID_TAG = hl7_clark_tag("setId")
SECTION_TAG = hl7_clark_tag("section")
OBSERVATION_TAG = hl7_clark_tag("observation")
ID_TAG = hl7_clark_tag("id")
TEMPLATE_ID_TAG = hl7_clark_tag("templateId")
CODE_TAG = hl7_clark_tag("code")
EFFECTIVE_TIME_TAG = hl7_clark_tag("effectiveTime")
