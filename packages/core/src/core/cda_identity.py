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
from enum import StrEnum
from typing import Optional, Tuple, TypeAlias

from lxml import etree

from core.constants import (
    CODE_KEY_ATTRS,
    DIRECT_ID_KEY_ATTRS,
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
    f"{{{HL7_NS}}}{local_name}"
    for local_name in sorted(CDA_CLINICAL_STATEMENT_LOCAL_NAMES)
)


CDA_SINGLE_STATEMENT_WRAPPER_LOCAL_NAMES = frozenset(
    {
        "entry",
        "entryRelationship",
        "component",
    }
)

DIRECT_TEMPLATE_ID_TAG = f"{{{HL7_NS}}}templateId"
DIRECT_ID_TAG = f"{{{HL7_NS}}}id"
SECTION_TAG = f"{{{HL7_NS}}}section"
ROOT_ATTRIBUTE, EXTENSION_ATTRIBUTE = ROOT_EXTENSION_KEY_ATTRS
CODE_ATTRIBUTE, CODE_SYSTEM_ATTRIBUTE = CODE_KEY_ATTRS
ELEMENTS_HAVING_ROOT_EXTENSION_IDENTITY = frozenset(
    {
        "id",
        "templateId",
        "setId",
    }
)


@dataclass(frozen=True, order=True)
class RootExtension:
    """
    Comparable CDA match fields from root and optional extension.

    CDA <id> and <templateId> elements both use root as the main identifier.
    The extension, when present, further qualifies that identifier. Missing
    extensions are represented as an empty string so fields can be compared
    and sorted consistently.
    """

    root: str
    extension: str = ""


class IdAttributeKeySource(StrEnum):
    """Stable-key sources that use direct ID/id attributes."""

    DIRECT = "direct"
    NESTED_CLINICAL_STATEMENT = "nested_clinical_statement"


class ElementSetKeySource(StrEnum):
    """Stable-key sources that use root/extension fields from element sets."""

    DIRECT_CHILD = "direct_child"
    NESTED_CLINICAL_STATEMENT = "nested_clinical_statement"
    NESTED_SECTION = "nested_section"


@dataclass(frozen=True)
class IdAttributeKey:
    """Stable key from ID/id attribute fields plus their source."""

    source: IdAttributeKeySource
    name: str
    value: str


@dataclass(frozen=True)
class RootExtensionKey:
    """Stable key from root/extension fields on id-like elements."""

    root: str
    extension: str = ""


@dataclass(frozen=True)
class CodeKey:
    """Stable key from code/codeSystem match fields."""

    code: str
    code_system: str


@dataclass(frozen=True)
class IdElementSetKey:
    """Stable key from a source plus root/extension fields on <id> elements."""

    source: ElementSetKeySource
    root_extensions: tuple[RootExtension, ...]


@dataclass(frozen=True)
class TemplateIdElementSetKey:
    """Stable key from a source plus root/extension fields on <templateId>."""

    source: ElementSetKeySource
    root_extensions: tuple[RootExtension, ...]


StableKey: TypeAlias = (
    IdAttributeKey
    | RootExtensionKey
    | CodeKey
    | IdElementSetKey
    | TemplateIdElementSetKey
)

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
        qualified_name.namespace == HL7_NS and qualified_name.localname in local_names
    )


def _is_cda_clinical_statement(element: etree._Element) -> bool:
    """Return True when element is a CDA clinical statement element."""
    return _is_hl7_element_with_local_name(
        element,
        CDA_CLINICAL_STATEMENT_LOCAL_NAMES,
    )


def _is_cda_single_clinical_statement_wrapper(element: etree._Element) -> bool:
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

    if _is_cda_single_clinical_statement_wrapper(element):
        return _single_direct_clinical_statement_child(element)

    return None


def _root_extension_from_element(
    element: etree._Element,
) -> Optional[RootExtension]:
    """Return root/extension fields from one element, or None without root."""
    root_value = element.get(ROOT_ATTRIBUTE)
    if not root_value:
        return None

    return RootExtension(
        root=root_value,
        extension=element.get(EXTENSION_ATTRIBUTE) or "",
    )


def _direct_child_root_extensions_for_tag(
    element: etree._Element,
    child_tag: str,
) -> tuple[RootExtension, ...]:
    """
    Return sorted root/extensions from direct children matching child_tag.

    Missing extensions are normalized to an empty string. The returned tuple is
    sorted and deduplicated so document order and duplicate declarations do not
    affect the exact key. Children without @root are skipped because they are
    not useful for identity matching.
    """
    root_extensions: set[RootExtension] = set()

    for child_element in element.iterchildren(tag=child_tag):
        root_extension = _root_extension_from_element(child_element)
        if root_extension is not None:
            root_extensions.add(root_extension)

    return tuple(sorted(root_extensions))


def _nested_section_root_extensions_for_tag(
    element: etree._Element,
    *,
    child_tag: str,
    limit: int = 12,
) -> tuple[RootExtension, ...]:
    """
    Return root/extensions collected from descendant sections, or no key if too broad.

    Each descendant section contributes root/extensions from direct children
    matching child_tag. The complete descendant section root/extension set is
    only used when it stays small enough to be a useful wrapper key. If the set
    grows beyond limit, return no key rather than a document-order-dependent
    partial key.
    """
    if limit <= 0:
        return ()

    nested_section_root_extensions: set[RootExtension] = set()

    for section_element in element.iterdescendants(tag=SECTION_TAG):
        nested_section_root_extensions.update(
            _direct_child_root_extensions_for_tag(section_element, child_tag)
        )
        if len(nested_section_root_extensions) > limit:
            return ()

    return tuple(sorted(nested_section_root_extensions))


def _id_attribute_key(elem: etree._Element) -> Optional[IdAttributeKey]:
    """Return a standalone ID/id attribute key, if present."""
    for attr in DIRECT_ID_KEY_ATTRS:
        attr_value = elem.get(attr)
        if attr_value:
            return IdAttributeKey(
                source=IdAttributeKeySource.DIRECT,
                name=attr,
                value=attr_value,
            )
    return None


def _root_extension_key(elem: etree._Element) -> Optional[RootExtensionKey]:
    """Return a direct root/extension key for matching CDA element names."""
    if localname(elem) not in ELEMENTS_HAVING_ROOT_EXTENSION_IDENTITY:
        return None

    root_extension = _root_extension_from_element(elem)
    if root_extension is None:
        return None

    return RootExtensionKey(
        root=root_extension.root,
        extension=root_extension.extension,
    )


def _code_key(elem: etree._Element) -> Optional[CodeKey]:
    """Return a direct coded-concept key only when codeSystem is present."""
    code_value = elem.get(CODE_ATTRIBUTE)
    code_system = elem.get(CODE_SYSTEM_ATTRIBUTE)
    if not (code_value and code_system):
        return None

    return CodeKey(code=code_value, code_system=code_system)


def _attribute_key(elem: etree._Element) -> Optional[StableKey]:
    """
    Return an attribute-derived key for elem, if present.

    ID/id attributes are standalone keys. CDA root/extension attributes are
    only treated as keys on id/templateId-like elements, and code is only
    treated as a key when codeSystem is present on the same element.
    """
    id_attribute_key = _id_attribute_key(elem)
    if id_attribute_key:
        return id_attribute_key

    root_extension_key = _root_extension_key(elem)
    if root_extension_key:
        return root_extension_key

    code_key = _code_key(elem)
    if code_key:
        return code_key

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
    joined = "|".join(
        normalize_text(cell.text) for cell in cells if normalize_text(cell.text)
    )
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
      1. Element's own true direct attribute keys
      2. Direct child <id> root + optional extension identities
      3. Nested clinical statement direct ID/id attribute key
      4. Nested clinical statement child <id> identities
      5. Nested section <id> identities
      6. Direct child <templateId> root + extension identities
      7. Nested section templateId root + extension identities
      8. Nested clinical statement templateId root + extension identities
    """
    attribute_key = _attribute_key(elem)
    if attribute_key:
        return attribute_key

    child_id_root_extensions = _direct_child_root_extensions_for_tag(
        elem,
        DIRECT_ID_TAG,
    )
    if child_id_root_extensions:
        return IdElementSetKey(
            source=ElementSetKeySource.DIRECT_CHILD,
            root_extensions=child_id_root_extensions,
        )

    clinical_statement_element = _clinical_statement_for_identity(elem)
    if clinical_statement_element is not None:
        stmt_id_attribute_key = _id_attribute_key(
            clinical_statement_element,
        )
        if stmt_id_attribute_key:
            return IdAttributeKey(
                source=IdAttributeKeySource.NESTED_CLINICAL_STATEMENT,
                name=stmt_id_attribute_key.name,
                value=stmt_id_attribute_key.value,
            )

        stmt_child_id_root_extensions = _direct_child_root_extensions_for_tag(
            clinical_statement_element,
            DIRECT_ID_TAG,
        )
        if stmt_child_id_root_extensions:
            return IdElementSetKey(
                source=ElementSetKeySource.NESTED_CLINICAL_STATEMENT,
                root_extensions=stmt_child_id_root_extensions,
            )

    nested_section_id_root_extensions = _nested_section_root_extensions_for_tag(
        elem,
        child_tag=DIRECT_ID_TAG,
    )
    if nested_section_id_root_extensions:
        return IdElementSetKey(
            source=ElementSetKeySource.NESTED_SECTION,
            root_extensions=nested_section_id_root_extensions,
        )

    child_template_id_root_extensions = _direct_child_root_extensions_for_tag(
        elem,
        DIRECT_TEMPLATE_ID_TAG,
    )
    if child_template_id_root_extensions:
        return TemplateIdElementSetKey(
            source=ElementSetKeySource.DIRECT_CHILD,
            root_extensions=child_template_id_root_extensions,
        )

    nested_section_template_id_root_extensions = _nested_section_root_extensions_for_tag(
        elem,
        child_tag=DIRECT_TEMPLATE_ID_TAG,
    )
    if nested_section_template_id_root_extensions:
        return TemplateIdElementSetKey(
            source=ElementSetKeySource.NESTED_SECTION,
            root_extensions=nested_section_template_id_root_extensions,
        )

    if clinical_statement_element is not None:
        stmt_template_id_root_extensions = _direct_child_root_extensions_for_tag(
            clinical_statement_element,
            DIRECT_TEMPLATE_ID_TAG,
        )
        if stmt_template_id_root_extensions:
            return TemplateIdElementSetKey(
                source=ElementSetKeySource.NESTED_CLINICAL_STATEMENT,
                root_extensions=stmt_template_id_root_extensions,
            )

    return None


# ---------------------------------------------------------------------------
# Clinical statement discriminators
# ---------------------------------------------------------------------------


def _statement_id_pair(elem: etree._Element) -> Optional[Tuple[str, str]]:
    """Return (root, extension) from the clinical statement's <id>, or None."""
    clinical_statement_element = _clinical_statement_for_identity(elem)
    if clinical_statement_element is not None:
        pair = _complete_attribute_pair(
            _xpath_first_element(clinical_statement_element, "./hl7:id"),
            "root",
            "extension",
        )
        if pair:
            return pair
    return _complete_attribute_pair(
        _xpath_first_element(elem, "./hl7:id"), "root", "extension"
    )


def _statement_code_pair(elem: etree._Element) -> Optional[Tuple[str, str]]:
    """Return (code, codeSystem) from the clinical statement's <code>, or None."""
    clinical_statement_element = _clinical_statement_for_identity(elem)
    if clinical_statement_element is not None:
        pair = _complete_attribute_pair(
            _xpath_first_element(clinical_statement_element, "./hl7:code"),
            "code",
            "codeSystem",
        )
        if pair:
            return pair
    return _complete_attribute_pair(
        _xpath_first_element(elem, "./hl7:code"), "code", "codeSystem"
    )


def _effective_time_discriminator(node: etree._Element) -> Optional[tuple]:
    """
    Return a discriminator tuple from a node's <effectiveTime>, trying each
    representation in order: point value, low/high interval, center, period.
    Returns None if no effectiveTime is found.
    """
    point_value = _xpath_first_attribute_value(node, "./hl7:effectiveTime/@value")
    if point_value:
        return ("effectiveTime.value", point_value)

    low_value = _xpath_first_attribute_value(node, "./hl7:effectiveTime/hl7:low/@value")
    high_value = _xpath_first_attribute_value(
        node, "./hl7:effectiveTime/hl7:high/@value"
    )
    if low_value or high_value:
        return ("effectiveTime.lowhigh", (low_value or "", high_value or ""))

    center_value = _xpath_first_attribute_value(
        node, "./hl7:effectiveTime/hl7:center/@value"
    )
    if center_value:
        return ("effectiveTime.center", center_value)

    period_value = _xpath_first_attribute_value(
        node, "./hl7:effectiveTime/hl7:period/@value"
    )
    period_unit = _xpath_first_attribute_value(
        node, "./hl7:effectiveTime/hl7:period/@unit"
    )
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
        (attr, elem.attrib[attr]) for attr in WEAK_KEY_ATTRS if attr in elem.attrib
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
            template_id_root_extensions = _direct_child_root_extensions_for_tag(
                current,
                DIRECT_TEMPLATE_ID_TAG,
            )
            code_pair = _statement_code_pair(current) or ("", "")
            effective_time = _statement_effective_time(current) or ("", "")
            return (
                "organizer.ctx",
                (
                    template_id_root_extensions,
                    code_pair,
                    effective_time,
                ),
            )
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

    template_id_root_extensions = _direct_child_root_extensions_for_tag(
        elem,
        DIRECT_TEMPLATE_ID_TAG,
    )
    if not template_id_root_extensions:
        return None

    effective_time = _statement_effective_time(elem) or ("", "")
    organizer = _organizer_context(elem)
    code_pair = _statement_code_pair(elem) or ("", "")
    return (
        "ctx",
        (
            template_id_root_extensions,
            effective_time,
            organizer,
            code_pair,
        ),
    )
