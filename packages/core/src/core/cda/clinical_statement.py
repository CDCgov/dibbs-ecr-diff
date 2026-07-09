"""CDA clinical-statement detection and wrapper navigation."""

from lxml import etree

from core.constants import HL7_NS
from core.xml_utils import hl7_clark_tag

CDA_CLINICAL_STATEMENT_LOCAL_NAMES = frozenset(
    {
        "act",
        "observation",
        "encounter",
        "procedure",
        "substanceAdministration",
        "supply",
        "organizer",
        "observationMedia",
        "regionOfInterest",
    }
)

CDA_CLINICAL_STATEMENT_TAGS = tuple(
    hl7_clark_tag(local_name)
    for local_name in sorted(CDA_CLINICAL_STATEMENT_LOCAL_NAMES)
)


CDA_CLINICAL_STATEMENT_WRAPPER_LOCAL_NAMES = frozenset(
    {
        "entry",
        "entryRelationship",
        "component",
    }
)


def _is_hl7_element_with_local_name(
    element: etree._Element,
    local_names: frozenset[str],
) -> bool:
    """Return True when element is in the HL7 namespace and local_names."""
    if not isinstance(element.tag, str):
        return False

    qualified_name = etree.QName(element.tag)
    return (
        qualified_name.namespace == HL7_NS and qualified_name.localname in local_names
    )


def _is_cda_clinical_statement(element: etree._Element) -> bool:
    """Return True when element is a CDA clinical statement element."""
    return _is_hl7_element_with_local_name(
        element,
        CDA_CLINICAL_STATEMENT_LOCAL_NAMES,
    )


def _is_cda_statement_wrapper_name(element: etree._Element) -> bool:
    """Return True when element has a CDA statement-wrapper element name."""
    return _is_hl7_element_with_local_name(
        element,
        CDA_CLINICAL_STATEMENT_WRAPPER_LOCAL_NAMES,
    )


def _single_direct_clinical_statement_child(
    element: etree._Element,
) -> etree._Element | None:
    """Return the direct clinical statement child when exactly one exists.

    Returning None for zero or multiple direct statement children avoids using
    document order as a key when the structure is not a clinical statement
    wrapper.
    """
    clinical_statement_child = None

    for child_element in element.iterchildren(tag=CDA_CLINICAL_STATEMENT_TAGS):
        if clinical_statement_child is not None:
            return None
        clinical_statement_child = child_element

    return clinical_statement_child


def clinical_statement_element_for_key_derivation(
    element: etree._Element,
) -> etree._Element | None:
    """Return the clinical statement element that should be used for key derivation.

    Handles:
      - a clinical statement element itself, such as <observation>
      - clinical statement wrappers such as <entry> and <entryRelationship>
      - <component> elements only when they directly contain exactly one
        clinical statement child

    CDA <component> is overloaded: document and section components may wrap
    structuredBody or section elements and should not be treated as clinical
    statement wrappers.

    Returns None when no suitable clinical statement is found.
    """
    if _is_cda_clinical_statement(element):
        return element

    if _is_cda_statement_wrapper_name(element):
        return _single_direct_clinical_statement_child(element)

    return None
