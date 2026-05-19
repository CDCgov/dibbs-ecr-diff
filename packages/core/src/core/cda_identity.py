"""
core/cda_identity.py

CDA-domain-specific identity and discriminator key derivation.

This is the most domain-specific module in the package — it encodes knowledge
of CDA document structure (templateId, clinical statement act classes,
effectiveTime representations, narrative table/row conventions) to derive
stable keys for matching elements across document versions.

If the tool ever needs to support a different CDA profile or implementation
guide, this is the primary file to modify.
"""
from dataclasses import dataclass
from typing import Optional, Tuple

from lxml import etree

from core.constants import KEY_ATTRS, HL7_NAMESPACE, HL7_NS
from core.xml_utils import (
    _complete_attribute_pair, _xpath_first_attribute_value, _collect_subtree_attribute_values, _xpath_first_element,
    fingerprint, localname, normalize_text,
)

CDA_CLINICAL_STATEMENT_LOCAL_NAMES = frozenset({
    "act",
    "observation",
    "encounter",
    "procedure",
    "substanceAdministration",
    "supply",
    "organizer",
    "observationMedia",
    "regionOfInterest",
})


CDA_CLINICAL_STATEMENT_WRAPPER_LOCAL_NAMES = frozenset({
    "entry",
    "entryRelationship",
    "component",
})

DIRECT_TEMPLATE_ID_TAG = f"{{{HL7_NS}}}templateId"
ROOT_ATTRIBUTE = "root"
EXTENSION_ATTRIBUTE = "extension"

@dataclass(frozen=True, order=True)
class TemplateIdIdentity:
    """
    Comparable identity values from a CDA <templateId> element.

    The root identifies the template. The extension, when present, further
    qualifies that template identifier. Missing extensions are represented as
    an empty string so identities can be compared and sorted consistently.
    """

    root: str
    extension: str = ""

TemplateIdIdentities = tuple[TemplateIdIdentity, ...]

# ---------------------------------------------------------------------------
# CDA clinical-statement navigation helpers
# ---------------------------------------------------------------------------

def _is_hl7_element_with_local_name(
        element: etree._Element,
        local_names: frozenset[str],
) -> bool:
    """
    Return True when element is in the HL7 namespace and is in local_names.
    """
    if not isinstance(element.tag, str):
        return False
    
    qualified_name = etree.QName(element.tag)
    return (
            qualified_name.namespace == HL7_NS
            and qualified_name.localname in local_names
    )


def _is_cda_clinical_statement(element: etree._Element) -> bool:
    """Return True when element is a CDA clinical statement element."""
    return _is_hl7_element_with_local_name(
        element,
        CDA_CLINICAL_STATEMENT_LOCAL_NAMES,
    )


def _first_direct_clinical_statement_child(
        element: etree._Element,
) -> Optional[etree._Element]:
    """
    Return the first direct child that is a CDA clinical statement element.

    This intentionally checks only direct children. A deep descendant search
    could accidentally select a nested statement that is not the primary 
    statement represented by the current wrapper.
    """
    for child_element in element.iterchildren(tag=etree.Element):
        if _is_cda_clinical_statement(child_element):
            return child_element

    return None


def _first_clinical_statement_wrapped_by_direct_child(
        element: etree._Element,
) -> Optional[etree._Element]:
    """
    Return the first clinical statement found inside a direct CDA wrapper child.

    Checks direct wrapper children such as <entry>, <entryRelationship>, or a 
    <component> that directly contains a clinical statement.
    """
    for child_element in element.iterchildren(tag=etree.Element):
        if _is_hl7_element_with_local_name(
                child_element,
                CDA_CLINICAL_STATEMENT_WRAPPER_LOCAL_NAMES,
        ):
            clinical_statement = _first_direct_clinical_statement_child(child_element)
            if clinical_statement is not None:
                return clinical_statement

    return None


def _clinical_statement_for_identity(
        element: etree._Element,
) -> Optional[etree._Element]:
    """
    Return the clinical statement element that should be used for identity.

    Handles:
      - a clinical statement element itself, such as <observation>
      - elements whose direct child is a statement, such as <entry>
      - parents with direct <entry>, <entryRelationship>, or <component>
        children that wrap a clinical statement

    Returns None when no suitable clinical statement is found.
    """
    if _is_cda_clinical_statement(element):
        return element

    direct_clinical_statement_child = _first_direct_clinical_statement_child(element)
    if direct_clinical_statement_child is not None:
        return direct_clinical_statement_child

    wrapped_clinical_statement_grandchild = _first_clinical_statement_wrapped_by_direct_child(
        element,
    )
    if wrapped_clinical_statement_grandchild is not None:
        return wrapped_clinical_statement_grandchild

    return None


def _template_root(elem: etree._Element) -> Optional[str]:
    """Return the @root of the first <templateId> child of elem, or None."""
    return _xpath_first_attribute_value(elem, "./hl7:templateId/@root")

#replace _template_root with this method, but make sure it's return type is compatible through the stack
def _direct_template_id_identities(
        element: etree._Element,
) -> TemplateIdIdentities:
    """
    Return sorted identities from direct <templateId> children.

    Template IDs are treated as an unordered set because their document order
    should not affect identity matching. Duplicate template IDs are returned
    only once. Template IDs without @root are skipped because they are not
    useful for identity matching.
    """
    template_id_identities: set[TemplateIdIdentity] = set()

    for template_id_element in element.iterchildren(
            tag=DIRECT_TEMPLATE_ID_TAG,
    ):
        template_id_root = template_id_element.get(ROOT_ATTRIBUTE)
        if not template_id_root:
            continue

        template_id_extension = (
                template_id_element.get(EXTENSION_ATTRIBUTE) or ""
        )

        template_id_identities.add(
            TemplateIdIdentity(
                root=template_id_root,
                extension=template_id_extension,
            ),
        )

    return tuple(sorted(template_id_identities))


# ---------------------------------------------------------------------------
# Narrative table / row identity
# ---------------------------------------------------------------------------

def narrative_table_key(elem: etree._Element) -> Optional[tuple]:
    """
    Derive a stable identity key for a CDA narrative <table> element.

    Prefers the column header labels from <thead>; falls back to the text of
    the first cell in the first row.  Returns None for non-table elements.
    """
    if localname(elem) != "table":
        return None

    headers = elem.xpath("./hl7:thead/hl7:tr[1]/hl7:th", namespaces=HL7_NAMESPACE)
    if headers:
        labels = [normalize_text(th.text) for th in headers if normalize_text(th.text)]
        if labels:
            return ("table.headers", tuple(labels))

    first_cell = elem.xpath(
        ".//hl7:tr[1]/*[self::hl7:th or self::hl7:td][1]", namespaces=HL7_NAMESPACE
    )
    if first_cell:
        text = normalize_text(first_cell[0].text)
        if text:
            return ("table.first_cell", text)

    return None


def narrative_row_key(elem: etree._Element) -> Optional[tuple]:
    """
    Derive a stable identity key for a CDA narrative <tr> element.

    Prefers the text of the first cell; falls back to all cell text joined
    with a pipe separator.  Returns None for non-tr elements.
    """
    if localname(elem) != "tr":
        return None

    first_cell = elem.xpath("./hl7:td[1] | ./hl7:th[1]", namespaces=HL7_NAMESPACE)
    if first_cell:
        text = normalize_text(first_cell[0].text)
        if text:
            return ("row.first_cell", text)

    cells = elem.xpath("./hl7:td | ./hl7:th", namespaces=HL7_NAMESPACE)
    joined = "|".join(normalize_text(cell.text) for cell in cells if normalize_text(cell.text))
    if joined:
        return ("row.cells", joined)

    return None


# ---------------------------------------------------------------------------
# Stable identity keys (used for element matching across versions)
# ---------------------------------------------------------------------------

def stable_key(elem: etree._Element) -> Optional[tuple]:
    """
    Derive the most specific stable identity key available for elem.

    The key is used to match elements across before/after versions.  Keys are
    tried from most to least specific; the first match wins.

    Priority:
      1. Direct KEY_ATTRS attributes (id, root, extension, code, moodCode, …)
      2. Child <templateId> root + extension
      3. Child <id> root + optional extension
      4. Nested section templateId roots (for component/section wrappers)
      5. Nested entry statement id (root + extension)
      6. Nested entry statement templateId roots
      7. Any descendant id (root + extension)
    """
    items = [(attr, elem.attrib[attr]) for attr in KEY_ATTRS if attr in elem.attrib]
    if items:
        return ("@attrs", tuple(items))

    template_root = _xpath_first_attribute_value(elem, "./hl7:templateId/@root")
    if template_root:
        template_ext = _xpath_first_attribute_value(elem, "./hl7:templateId/@extension") or ""
        return ("templateId", ("root", template_root), ("extension", template_ext))

    id_root = _xpath_first_attribute_value(elem, "./hl7:id/@root")
    if id_root:
        id_ext = _xpath_first_attribute_value(elem, "./hl7:id/@extension")
        return ("id", ("root", id_root), ("extension", id_ext)) if id_ext \
            else ("id", ("root", id_root))

    section_template_roots = _collect_subtree_attribute_values(
        elem=elem,
        node_path=".//hl7:section/hl7:templateId",
        attribute_name="root",
        limit=6,
    )
    if section_template_roots:
        return ("nested.section.templateId.roots", tuple(sorted(section_template_roots)))

    clinical_statement_element = _clinical_statement_for_identity(elem)
    if clinical_statement_element is not None:
        stmt_id_root = _xpath_first_attribute_value(clinical_statement_element, "./hl7:id/@root")
        stmt_id_ext  = _xpath_first_attribute_value(clinical_statement_element, "./hl7:id/@extension")
        if stmt_id_root and stmt_id_ext:
            return ("nested.entry.statement.id",
                    ("root", stmt_id_root), ("extension", stmt_id_ext))

        stmt_template_roots = _collect_subtree_attribute_values(
            elem=clinical_statement_element,
            node_path="./hl7:templateId",
            attribute_name="root",
            limit=6,
        )
        if stmt_template_roots:
            return ("nested.entry.statement.templateId.roots",
                    tuple(sorted(stmt_template_roots)))

    any_id_root = _xpath_first_attribute_value(elem, ".//hl7:id/@root")
    any_id_ext  = _xpath_first_attribute_value(elem, ".//hl7:id/@extension")
    if any_id_root and any_id_ext:
        return ("nested.any.id", ("root", any_id_root), ("extension", any_id_ext))

    return None


# ---------------------------------------------------------------------------
# Clinical statement discriminators
# ---------------------------------------------------------------------------

def _statement_id_pair(elem: etree._Element) -> Optional[Tuple[str, str]]:
    """Return (root, extension) from the clinical statement's <id>, or None."""
    clinical_statement_element = _clinical_statement_for_identity(elem)
    if clinical_statement_element is not None:
        pair = _complete_attribute_pair(_xpath_first_element(clinical_statement_element, "./hl7:id"), "root", "extension")
        if pair:
            return pair
    return _complete_attribute_pair(_xpath_first_element(elem, "./hl7:id"), "root", "extension")


def _statement_code_pair(elem: etree._Element) -> Optional[Tuple[str, str]]:
    """Return (code, codeSystem) from the clinical statement's <code>, or None."""
    clinical_statement_element = _clinical_statement_for_identity(elem)
    if clinical_statement_element is not None:
        pair = _complete_attribute_pair(_xpath_first_element(clinical_statement_element, "./hl7:code"), "code", "codeSystem")
        if pair:
            return pair
    return _complete_attribute_pair(_xpath_first_element(elem, "./hl7:code"), "code", "codeSystem")


def _observation_value_discriminator(elem: etree._Element) -> Optional[tuple]:
    """
    Return a discriminator tuple derived from an observation's <value> element.
    Tries coded value, numeric value, then text content — returns None if none found.
    """
    clinical_statement_element = _clinical_statement_for_identity(elem)
    observation = clinical_statement_element if (
            clinical_statement_element is not None and localname(clinical_statement_element) == "observation"
    ) else None

    def _from_node(node: etree._Element) -> Optional[tuple]:
        value_elem = _xpath_first_element(node, "./hl7:value")
        if value_elem is None:
            return None
        code = value_elem.get("code")
        code_system = value_elem.get("codeSystem")
        if code and code_system:
            return ("value.code", (code, code_system))
        numeric_value = value_elem.get("value")
        if numeric_value:
            return ("value.value", numeric_value)
        text_value = normalize_text(value_elem.text)
        if text_value:
            return ("value.text", text_value)
        return None

    if observation is not None:
        discriminator = _from_node(observation)
        if discriminator:
            return ("obs", discriminator)
    return _from_node(elem)


def _effective_time_discriminator(node: etree._Element) -> Optional[tuple]:
    """
    Return a discriminator tuple from a node's <effectiveTime>, trying each
    representation in order: point value, low/high interval, center, period.
    Returns None if no effectiveTime is found.
    """
    point_value = _xpath_first_attribute_value(node, "./hl7:effectiveTime/@value")
    if point_value:
        return ("effectiveTime.value", point_value)

    low_value  = _xpath_first_attribute_value(node, "./hl7:effectiveTime/hl7:low/@value")
    high_value = _xpath_first_attribute_value(node, "./hl7:effectiveTime/hl7:high/@value")
    if low_value or high_value:
        return ("effectiveTime.lowhigh", (low_value or "", high_value or ""))

    center_value = _xpath_first_attribute_value(node, "./hl7:effectiveTime/hl7:center/@value")
    if center_value:
        return ("effectiveTime.center", center_value)

    period_value = _xpath_first_attribute_value(node, "./hl7:effectiveTime/hl7:period/@value")
    period_unit  = _xpath_first_attribute_value(node, "./hl7:effectiveTime/hl7:period/@unit")
    if period_value or period_unit:
        return ("effectiveTime.period", (period_value or "", period_unit or ""))

    return None


def _statement_effective_time(elem: etree._Element) -> Optional[tuple]:
    """
    Return an effectiveTime discriminator from the nested clinical statement
    if present, otherwise from elem itself.
    """
    clinical_statement_element = _clinical_statement_for_identity(elem)
    if clinical_statement_element is not None:
        effective_time = _effective_time_discriminator(clinical_statement_element)
        if effective_time:
            return effective_time
    return _effective_time_discriminator(elem)


def secondary_discriminator(elem: etree._Element) -> tuple:
    """
    Return the best available secondary discriminator for elem.

    Used after primary bucket matching when a bucket contains multiple elements
    that share the same templateId root.  Tried in priority order:
      narrative table key → narrative row key → statement id → statement code
      → effectiveTime → fingerprint
    """
    table_key = narrative_table_key(elem)
    if table_key:
        return ("narr_table", table_key)

    row_key = narrative_row_key(elem)
    if row_key:
        return ("narr_row", row_key)

    id_pair = _statement_id_pair(elem)
    if id_pair:
        return ("id", id_pair)

    code_pair = _statement_code_pair(elem)
    if code_pair:
        return ("code", code_pair)

    effective_time = _statement_effective_time(elem)
    if effective_time:
        return ("time", effective_time)

    return ("fp", fingerprint(elem))


# ---------------------------------------------------------------------------
# Prefer-updates soft context key
# ---------------------------------------------------------------------------

def _organizer_context(elem: etree._Element) -> tuple:
    """
    Walk up the ancestor chain to find the nearest enclosing <organizer> and
    return a signature tuple for it.  Used so that observations nested inside
    different organizers (lab panels) are not incorrectly paired across panels.
    """
    current = elem.getparent()
    while current is not None:
        if localname(current) == "organizer":
            id_pair = _statement_id_pair(current)
            if id_pair:
                return ("organizer.id", id_pair)
            template = _template_root(current) or ""
            code_pair = _statement_code_pair(current) or ("", "")
            effective_time = _statement_effective_time(current) or ("", "")
            return ("organizer.ctx", (template, code_pair, effective_time))
        current = current.getparent()
    return ("organizer.none", "")


def soft_context_key(elem: etree._Element) -> Optional[tuple]:
    """
    Return a soft context key.

    When multiple elements share the same templateId, this key tries to pair
    them as updates (same logical entity, changed content) rather than as
    add+delete pairs.  Returns None if no useful context can be derived.
    """
    id_pair = _statement_id_pair(elem)
    if id_pair:
        return ("id", id_pair)

    template = _template_root(elem)
    if not template:
        return None

    effective_time = _statement_effective_time(elem) or ("", "")
    organizer      = _organizer_context(elem)
    code_pair      = _statement_code_pair(elem) or ("", "")
    return ("ctx", (template, effective_time, organizer, code_pair))