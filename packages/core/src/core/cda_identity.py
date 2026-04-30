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

from typing import List, Optional, Tuple

from lxml import etree

from core.constants import KEY_ATTRS, NS
from core.xml_utils import (
    _attr_pair, _xpath_attr, _xpath_attrs, _xpath_node,
    fingerprint, localname, normalize_text,
)


# ---------------------------------------------------------------------------
# CDA clinical-statement navigation helpers
# ---------------------------------------------------------------------------

def _clinical_statement_xpath() -> str:
    """
    XPath that selects the primary clinical statement child of an <entry> element.
    Covers all act classes that can appear directly under <entry> in CDA.
    """
    return (
        "./hl7:entry"
        "/*[self::hl7:act or self::hl7:observation or self::hl7:encounter"
        " or self::hl7:procedure or self::hl7:substanceAdministration"
        " or self::hl7:supply or self::hl7:organizer]"
    )


def _get_statement(elem: etree._Element) -> Optional[etree._Element]:
    """
    Return the primary clinical statement node nested under elem (via an <entry>),
    or None if elem does not contain one.
    """
    return _xpath_node(elem, _clinical_statement_xpath())


def _template_root(elem: etree._Element) -> Optional[str]:
    """Return the @root of the first <templateId> child of elem, or None."""
    return _xpath_attr(elem, "./hl7:templateId/@root")


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

    headers = elem.xpath("./hl7:thead/hl7:tr[1]/hl7:th", namespaces=NS)
    if headers:
        labels = [normalize_text(th.text) for th in headers if normalize_text(th.text)]
        if labels:
            return ("table.headers", tuple(labels))

    first_cell = elem.xpath(
        ".//hl7:tr[1]/*[self::hl7:th or self::hl7:td][1]", namespaces=NS
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

    first_cell = elem.xpath("./hl7:td[1] | ./hl7:th[1]", namespaces=NS)
    if first_cell:
        text = normalize_text(first_cell[0].text)
        if text:
            return ("row.first_cell", text)

    cells = elem.xpath("./hl7:td | ./hl7:th", namespaces=NS)
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

    template_root = _xpath_attr(elem, "./hl7:templateId/@root")
    if template_root:
        template_ext = _xpath_attr(elem, "./hl7:templateId/@extension") or ""
        return ("templateId", ("root", template_root), ("extension", template_ext))

    id_root = _xpath_attr(elem, "./hl7:id/@root")
    if id_root:
        id_ext = _xpath_attr(elem, "./hl7:id/@extension")
        return ("id", ("root", id_root), ("extension", id_ext)) if id_ext \
            else ("id", ("root", id_root))

    section_template_roots = _xpath_attrs(
        elem, ".//hl7:section/hl7:templateId/@root", limit=8
    )
    if section_template_roots:
        return ("nested.section.templateId.roots", tuple(sorted(section_template_roots)))

    statement = _get_statement(elem)
    if statement is not None:
        stmt_id_root = _xpath_attr(statement, "./hl7:id/@root")
        stmt_id_ext  = _xpath_attr(statement, "./hl7:id/@extension")
        if stmt_id_root and stmt_id_ext:
            return ("nested.entry.statement.id",
                    ("root", stmt_id_root), ("extension", stmt_id_ext))

        stmt_template_roots = _xpath_attrs(statement, "./hl7:templateId/@root", limit=8)
        if stmt_template_roots:
            return ("nested.entry.statement.templateId.roots",
                    tuple(sorted(stmt_template_roots)))

    any_id_root = _xpath_attr(elem, ".//hl7:id/@root")
    any_id_ext  = _xpath_attr(elem, ".//hl7:id/@extension")
    if any_id_root and any_id_ext:
        return ("nested.any.id", ("root", any_id_root), ("extension", any_id_ext))

    return None


# ---------------------------------------------------------------------------
# Clinical statement discriminators
# ---------------------------------------------------------------------------

def _statement_id_pair(elem: etree._Element) -> Optional[Tuple[str, str]]:
    """Return (root, extension) from the clinical statement's <id>, or None."""
    statement = _get_statement(elem)
    if statement is not None:
        pair = _attr_pair(_xpath_node(statement, "./hl7:id"), "root", "extension")
        if pair:
            return pair
    return _attr_pair(_xpath_node(elem, "./hl7:id"), "root", "extension")


def _statement_code_pair(elem: etree._Element) -> Optional[Tuple[str, str]]:
    """Return (code, codeSystem) from the clinical statement's <code>, or None."""
    statement = _get_statement(elem)
    if statement is not None:
        pair = _attr_pair(_xpath_node(statement, "./hl7:code"), "code", "codeSystem")
        if pair:
            return pair
    return _attr_pair(_xpath_node(elem, "./hl7:code"), "code", "codeSystem")


def _observation_value_discriminator(elem: etree._Element) -> Optional[tuple]:
    """
    Return a discriminator tuple derived from an observation's <value> element.
    Tries coded value, numeric value, then text content — returns None if none found.
    """
    statement = _get_statement(elem)
    observation = statement if (
            statement is not None and localname(statement) == "observation"
    ) else None

    def _from_node(node: etree._Element) -> Optional[tuple]:
        value_elem = _xpath_node(node, "./hl7:value")
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
    point_value = _xpath_attr(node, "./hl7:effectiveTime/@value")
    if point_value:
        return ("effectiveTime.value", point_value)

    low_value  = _xpath_attr(node, "./hl7:effectiveTime/hl7:low/@value")
    high_value = _xpath_attr(node, "./hl7:effectiveTime/hl7:high/@value")
    if low_value or high_value:
        return ("effectiveTime.lowhigh", (low_value or "", high_value or ""))

    center_value = _xpath_attr(node, "./hl7:effectiveTime/hl7:center/@value")
    if center_value:
        return ("effectiveTime.center", center_value)

    period_value = _xpath_attr(node, "./hl7:effectiveTime/hl7:period/@value")
    period_unit  = _xpath_attr(node, "./hl7:effectiveTime/hl7:period/@unit")
    if period_value or period_unit:
        return ("effectiveTime.period", (period_value or "", period_unit or ""))

    return None


def _statement_effective_time(elem: etree._Element) -> Optional[tuple]:
    """
    Return an effectiveTime discriminator from the nested clinical statement
    if present, otherwise from elem itself.
    """
    statement = _get_statement(elem)
    if statement is not None:
        effective_time = _effective_time_discriminator(statement)
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