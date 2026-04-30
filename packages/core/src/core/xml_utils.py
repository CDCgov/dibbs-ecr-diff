"""
core/xml_utils.py

Low-level XML utility functions with no dependency on diffing logic.
Covers text normalisation, XPath helpers, element construction,
fingerprinting, and self-contained XML snippet serialisation.
"""

from copy import deepcopy
from typing import Dict, List, Optional, Set, Tuple

from lxml import etree

from core.constants import HL7_NS, HL7_PREFIX, NS


# ---------------------------------------------------------------------------
# Text and tag helpers
# ---------------------------------------------------------------------------

def normalize_text(text: Optional[str]) -> str:
    """Collapse internal whitespace and strip leading/trailing whitespace."""
    if text is None:
        return ""
    return " ".join(text.split())


def localname(elem: etree._Element) -> str:
    """Return the local part of an element's tag, stripping any namespace URI."""
    return etree.QName(elem).localname


def _pfx(tag: str) -> str:
    """Prefixed tag for generated XPath output, e.g. 'id' → 'hl7:id'."""
    return f"{HL7_PREFIX}:{tag}"


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------

def fingerprint(elem: etree._Element) -> tuple:
    """
    Order-insensitive recursive fingerprint for an element subtree.

    Two elements with identical fingerprints are considered unchanged.
    Child fingerprints are sorted before hashing so that sibling reordering
    does not produce a false positive change — intentional for CDA where
    element order within a type group is often not semantically significant.
    """
    tag      = elem.tag
    text     = normalize_text(elem.text)
    attrs    = tuple(sorted(elem.attrib.items()))
    children = sorted(fingerprint(child) for child in elem if isinstance(child.tag, str))
    return (tag, text, attrs, tuple(children))


# ---------------------------------------------------------------------------
# XPath query helpers (all use the hl7: namespace prefix)
# ---------------------------------------------------------------------------

def _xpath_attr(elem: etree._Element, expr: str) -> Optional[str]:
    """Return the first string result of an XPath attribute expression, or None."""
    results = elem.xpath(expr, namespaces=NS)
    return results[0] if results else None


def _xpath_attrs(elem: etree._Element, expr: str, limit: int = 6) -> List[str]:
    """Return up to `limit` string results of an XPath attribute expression."""
    return list(elem.xpath(expr, namespaces=NS)[:limit])


def _xpath_node(elem: etree._Element, expr: str) -> Optional[etree._Element]:
    """Return the first element result of an XPath node expression, or None."""
    results = elem.xpath(expr, namespaces=NS)
    return results[0] if results else None


def _attr_pair(node: Optional[etree._Element],
               attr1: str, attr2: str) -> Optional[Tuple[str, str]]:
    """
    Return (attr1_value, attr2_value) from node if both attributes are present,
    otherwise None.
    """
    if node is None:
        return None
    value1 = node.get(attr1)
    value2 = node.get(attr2)
    return (value1, value2) if value1 and value2 else None


# ---------------------------------------------------------------------------
# Self-contained XML snippet serialisation
# ---------------------------------------------------------------------------

def _used_namespaces(elem: etree._Element) -> Set[str]:
    """
    Return the set of namespace URIs actually referenced within elem's subtree —
    either as element namespaces or as attribute namespaces (xsi:type, sdtc:valueSet, …).
    Only referenced namespaces need to appear in the snippet's xmlns declarations.
    """
    used: Set[str] = set()
    for node in elem.iter():
        if not isinstance(node.tag, str):
            continue
        namespace = etree.QName(node.tag).namespace
        if namespace:
            used.add(namespace)
        for attr_name in node.attrib:
            if attr_name.startswith("{"):
                used.add(etree.QName(attr_name).namespace)
    return used


def _snippet_nsmap(elem: etree._Element) -> dict:
    """
    Build a minimal namespace map for a self-contained XML snippet.

    Handles the common CDA pattern of declaring urn:hl7-org:v3 twice —
    once as the default namespace (xmlns=) and once as a named prefix
    (xmlns:cda=).  When both are present, lxml silently drops the default
    namespace when rebuilding an element, leaving snippets namespace-orphaned.

    Fix: always set the element's own namespace as the default (None key) first,
    then add only named prefixes for other namespaces actually used in the subtree,
    skipping any named alias that would duplicate the default namespace URI.
    """
    elem_namespace = etree.QName(elem.tag).namespace
    used_namespaces = _used_namespaces(elem)

    nsmap: dict = {}
    if elem_namespace:
        nsmap[None] = elem_namespace

    for prefix, uri in elem.nsmap.items():
        if prefix is None:
            continue
        if uri == elem_namespace:
            continue
        if uri in used_namespaces:
            nsmap[prefix] = uri

    return nsmap


def xml_string(elem: etree._Element) -> str:
    """
    Serialise elem to a self-contained, namespace-correct XML string.

    Elements extracted from within a CDA document inherit their namespace
    declarations from ancestor elements, so a plain etree.tostring() produces
    namespace-orphaned snippets with no xmlns= declaration.

    We fix this by rebuilding the snippet root with a minimal but complete
    namespace map so the output is valid standalone XML.
    """
    if elem.getparent() is None:
        return etree.tostring(elem, encoding="unicode", pretty_print=True,
                              with_tail=False)

    nsmap    = _snippet_nsmap(elem)
    new_root = etree.Element(elem.tag, attrib=elem.attrib, nsmap=nsmap)
    new_root.text = elem.text
    new_root.tail = None
    for child in elem:
        new_root.append(deepcopy(child))

    return etree.tostring(new_root, encoding="unicode", pretty_print=True,
                          with_tail=False)