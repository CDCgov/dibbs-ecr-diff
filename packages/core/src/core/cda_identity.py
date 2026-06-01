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
from typing import Optional, Tuple, TypeAlias

from lxml import etree

from core.constants import (
    CODE_KEY_ATTRS,
    DIRECT_ID_IDENTITY_ATTRS,
    HL7_NAMESPACE,
    HL7_NS,
    ROOT_EXTENSION_KEY_ATTRS,
    WEAK_KEY_ATTRS,
)
from core.xml_utils import (
    _complete_attribute_pair,
    _xpath_first_attribute_value,
    _xpath_first_element,
    fingerprint,
    localname,
    normalize_text,
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

CDA_CLINICAL_STATEMENT_TAGS = tuple(
    f"{{{HL7_NS}}}{local_name}"
    for local_name in sorted(CDA_CLINICAL_STATEMENT_LOCAL_NAMES)
)


CDA_SINGLE_STATEMENT_WRAPPER_LOCAL_NAMES = frozenset({
    "entry",
    "entryRelationship",
    "component",
})

DIRECT_TEMPLATE_ID_TAG = f"{{{HL7_NS}}}templateId"
DIRECT_ID_TAG = f"{{{HL7_NS}}}id"
SECTION_TAG = f"{{{HL7_NS}}}section"
ROOT_ATTRIBUTE, EXTENSION_ATTRIBUTE = ROOT_EXTENSION_KEY_ATTRS
CODE_ATTRIBUTE, CODE_SYSTEM_ATTRIBUTE = CODE_KEY_ATTRS
ELEMENTS_HAVING_ROOT_EXTENSION_IDENTITY = frozenset({
    "id",
    "templateId",
    "setId",
})

@dataclass(frozen=True, order=True)
class RootExtensionIdentity:
    """
    Comparable CDA identity values from root and optional extension.

    CDA <id> and <templateId> elements both use root as the main identifier.
    The extension, when present, further qualifies that identifier. Missing
    extensions are represented as an empty string so identities can be compared
    and sorted consistently.
    """

    root: str
    extension: str = ""

TemplateIdIdentities = tuple[RootExtensionIdentity, ...]
RootExtensionIdentities = tuple[RootExtensionIdentity, ...]
StableKey: TypeAlias = tuple

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


def _is_cda_single_statement_wrapper(element: etree._Element) -> bool:
    """Return True when element is a CDA wrapper for one clinical statement."""
    return _is_hl7_element_with_local_name(
        element,
        CDA_SINGLE_STATEMENT_WRAPPER_LOCAL_NAMES,
    )


def _single_direct_clinical_statement_child(
        element: etree._Element,
) -> Optional[etree._Element]:
    """
    Return the direct clinical statement child when exactly one exists.

    Returning None for zero or multiple direct statement children avoids using
    document order as identity when the structure is not a single-statement
    wrapper.
    """
    clinical_statement_child = None

    for child_element in element.iterchildren(tag=CDA_CLINICAL_STATEMENT_TAGS):
        if clinical_statement_child is not None:
            return None
        clinical_statement_child = child_element

    return clinical_statement_child


def _clinical_statement_for_identity(
        element: etree._Element,
) -> Optional[etree._Element]:
    """
    Return the clinical statement element that should be used for identity.

    Handles:
      - a clinical statement element itself, such as <observation>
      - single-statement wrappers such as <entry>, <entryRelationship>, or
        organizer <component> elements with exactly one direct statement child

    Returns None when no suitable clinical statement is found.
    """
    if _is_cda_clinical_statement(element):
        return element

    if _is_cda_single_statement_wrapper(element):
        return _single_direct_clinical_statement_child(element)

    return None


def _direct_template_id_identities(
        element: etree._Element,
) -> TemplateIdIdentities:
    """
    Return exact identities from direct <templateId> children.

    Each identity is the <templateId>'s root plus optional extension. Missing
    extensions are normalized to an empty string. The returned tuple is sorted
    and deduplicated so document order and duplicate declarations do not affect
    the exact key. Template IDs without @root are skipped because they are not
    useful for identity matching.
    """
    template_id_identities: set[RootExtensionIdentity] = set()

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
            RootExtensionIdentity(
                root=template_id_root,
                extension=template_id_extension,
            ),
        )

    return tuple(sorted(template_id_identities))


def _direct_child_id_identities(
        element: etree._Element,
) -> RootExtensionIdentities:
    """
    Return sorted identities from direct <id> children.

    The root and extension are read from the same <id> element. Duplicate IDs
    are collapsed, and IDs without @root are skipped.
    """
    child_id_identities: set[RootExtensionIdentity] = set()

    for child_id_element in element.iterchildren(tag=DIRECT_ID_TAG):
        child_id_root = child_id_element.get(ROOT_ATTRIBUTE)
        if not child_id_root:
            continue

        child_id_identities.add(
            RootExtensionIdentity(
                root=child_id_root,
                extension=child_id_element.get(EXTENSION_ATTRIBUTE) or "",
            ),
        )

    return tuple(sorted(child_id_identities))


def _nested_section_template_id_identities(
        element: etree._Element,
        limit: int = 12,
) -> TemplateIdIdentities:
    """
    Return templateId identities from descendant CDA section elements.

    Nested section identity is only used when the complete descendant section
    templateId set is small enough to be a useful wrapper key. If the set grows
    beyond limit, return no key rather than a document-order-dependent partial
    key.
    """
    if limit <= 0:
        return ()

    template_id_identities: set[RootExtensionIdentity] = set()

    for section_element in element.iterdescendants(tag=SECTION_TAG):
        template_id_identities.update(
            _direct_template_id_identities(section_element),
        )
        if len(template_id_identities) > limit:
            return ()

    return tuple(sorted(template_id_identities))


def _nested_section_id_identities(
        element: etree._Element,
        limit: int = 12,
) -> RootExtensionIdentities:
    """
    Return direct <id> identities from descendant CDA section elements.

    Nested section identity is only used when the complete descendant section
    ID set is small enough to be a useful wrapper key. If the set grows beyond
    limit, return no key rather than a document-order-dependent partial key.
    """
    if limit <= 0:
        return ()

    id_identities: set[RootExtensionIdentity] = set()

    for section_element in element.iterdescendants(tag=SECTION_TAG):
        id_identities.update(
            _direct_child_id_identities(section_element),
        )
        if len(id_identities) > limit:
            return ()

    return tuple(sorted(id_identities))


def _direct_id_attribute_identity(elem: etree._Element) -> Optional[StableKey]:
    """Return standalone direct ID/id attribute identity, if present."""
    for attr in DIRECT_ID_IDENTITY_ATTRS:
        attr_value = elem.get(attr)
        if attr_value:
            return ("@attrs", ((attr, attr_value),))
    return None


def _root_extension_attribute_identity(elem: etree._Element) -> Optional[StableKey]:
    """Return direct root/extension identity for matching CDA element names."""
    if localname(elem) not in ELEMENTS_HAVING_ROOT_EXTENSION_IDENTITY:
        return None

    root_value = elem.get(ROOT_ATTRIBUTE)
    if not root_value:
        return None

    parts = [(ROOT_ATTRIBUTE, root_value)]
    extension_value = elem.get(EXTENSION_ATTRIBUTE)
    if extension_value:
        parts.append((EXTENSION_ATTRIBUTE, extension_value))

    return ("@root", tuple(parts))


def _code_attribute_identity(elem: etree._Element) -> Optional[StableKey]:
    """Return direct coded-concept identity only when codeSystem is present."""
    code_value = elem.get(CODE_ATTRIBUTE)
    code_system = elem.get(CODE_SYSTEM_ATTRIBUTE)
    if not (code_value and code_system):
        return None

    return ("@code", (
        (CODE_ATTRIBUTE, code_value),
        (CODE_SYSTEM_ATTRIBUTE, code_system),
    ))


def _direct_attribute_identity(elem: etree._Element) -> Optional[StableKey]:
    """
    Return true direct-attribute identity for elem, if present.

    Direct ID/id attributes are standalone identities. CDA root/extension
    attributes are only treated as direct identities on id/templateId-like
    elements, and code is only treated as direct identity when codeSystem is
    present on the same element.
    """
    direct_id_identity = _direct_id_attribute_identity(elem)
    if direct_id_identity:
        return direct_id_identity

    root_extension_identity = _root_extension_attribute_identity(elem)
    if root_extension_identity:
        return root_extension_identity

    code_identity = _code_attribute_identity(elem)
    if code_identity:
        return code_identity

    return None


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

def stable_key(elem: etree._Element) -> Optional[StableKey]:
    """
    Derive the most specific stable identity key available for elem.

    The key is used to match elements across before/after versions.  Keys are
    tried from most to least specific; the first match wins.

    Priority:
      1. Element's own true direct identity attributes
      2. Direct child <id> root + optional extension identities
      3. Nested clinical statement direct ID/id attribute identity
      4. Nested clinical statement child <id> identities
      5. Nested section <id> identities
      6. Direct child <templateId> root + extension identities
      7. Nested section templateId root + extension identities
      8. Nested clinical statement templateId root + extension identities
    """
    direct_attribute_identity = _direct_attribute_identity(elem)
    if direct_attribute_identity:
        return direct_attribute_identity

    child_id_identities = _direct_child_id_identities(elem)
    if child_id_identities:
        return ("ids", child_id_identities)

    clinical_statement_element = _clinical_statement_for_identity(elem)
    if clinical_statement_element is not None:
        stmt_direct_id_identity = _direct_id_attribute_identity(
            clinical_statement_element,
        )
        if stmt_direct_id_identity:
            return ("nested.entry.statement.@attrs", stmt_direct_id_identity[1])

        stmt_child_id_identities = _direct_child_id_identities(
            clinical_statement_element,
        )
        if stmt_child_id_identities:
            return ("nested.entry.statement.ids", stmt_child_id_identities)

    section_id_identities = _nested_section_id_identities(elem)
    if section_id_identities:
        return ("nested.section.ids", section_id_identities)

    template_id_identities = _direct_template_id_identities(elem)
    if template_id_identities:
        return ("templateIds", template_id_identities)

    section_template_id_identities = _nested_section_template_id_identities(
        elem,
    )
    if section_template_id_identities:
        return ("nested.section.templateIds", section_template_id_identities)

    if clinical_statement_element is not None:
        stmt_template_id_identities = _direct_template_id_identities(
            clinical_statement_element,
        )
        if stmt_template_id_identities:
            return ("nested.entry.statement.templateIds",
                    stmt_template_id_identities)

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


def _weak_attribute_discriminator(elem: etree._Element) -> Optional[tuple]:
    """
    Return weak direct attributes for late in-bucket discrimination.

    These attributes are intentionally not stable identities. They are only
    used after stronger CDA discriminators fail, and include the element tag so
    their meaning stays scoped to the element kind being compared.
    """
    items = [
        (attr, elem.attrib[attr])
        for attr in WEAK_KEY_ATTRS
        if attr in elem.attrib
    ]
    if not items:
        return None
    return (elem.tag, tuple(items))


def secondary_discriminator(elem: etree._Element) -> tuple:
    """
    Return the best available secondary discriminator for elem.

    Used after primary bucket matching when a bucket contains multiple elements
    that share the same templateId identities. Tried in priority order:
      narrative table key -> narrative row key -> statement id -> statement code
      -> effectiveTime -> weak direct attributes -> fingerprint
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

    weak_attrs = _weak_attribute_discriminator(elem)
    if weak_attrs:
        return ("weak_attrs", weak_attrs)

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
            template_id_identities = _direct_template_id_identities(current)
            code_pair = _statement_code_pair(current) or ("", "")
            effective_time = _statement_effective_time(current) or ("", "")
            return ("organizer.ctx", (
                template_id_identities,
                code_pair,
                effective_time,
            ))
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

    template_id_identities = _direct_template_id_identities(elem)
    if not template_id_identities:
        return None

    effective_time = _statement_effective_time(elem) or ("", "")
    organizer      = _organizer_context(elem)
    code_pair      = _statement_code_pair(elem) or ("", "")
    return ("ctx", (
        template_id_identities,
        effective_time,
        organizer,
        code_pair,
    ))
