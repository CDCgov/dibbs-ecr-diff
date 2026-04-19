from collections import defaultdict

from lxml import etree


def _localname(elem: etree.Element) -> str:
    """Gets fully qualified localname."""
    return etree.QName(elem).localname


def is_table_cell_list(elems: list[etree.Element]) -> bool:
    """Checks if all children are table cell elements."""
    return bool(elems) and all(_localname(e) in ("td", "th") for e in elems)


def build_child_group(elem: etree.Element) -> dict[str, list[etree.Element]]:
    """Create map where tag -> list of child nodes."""
    # inits dict where missing keys auto-initialize to empty lists
    group = defaultdict(list)
    for c in elem:
        if isinstance(c.tag, str):
            group[c.tag].append(c)
    return group


def normalize_text(text: str | None) -> str:
    """Normalizes white-space and None to empty strings."""
    if text is None:
        return ""
    return " ".join(text.split())


def is_canonically_eq(elem_1: etree.Element, elem_2: etree.Element) -> bool:
    """Canonicalizes elements before doing a string comparison."""
    return etree.canonicalize(elem_1) == etree.canonicalize(elem_2)


def empty_copy(
    elem: etree.Element, namespace_map: dict[str | None, str] | None = None
) -> etree.Element:
    """Creates an empty copy of a given element."""
    elem = etree.Element(elem.tag, nsmap=namespace_map)
    elem.text = None
    elem.tail = None
    elem.attrib.clear()
    return elem
