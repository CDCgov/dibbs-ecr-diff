from typing import Any
from lxml import etree
from .models import HL7_NS

KEY_ATTRS = ("ID", "id", "root", "extension", "code")

def _first_xpath_node(elem: etree.Element, xpath_expr: str) -> Any | None:
    nodes = elem.xpath(xpath_expr, namespaces=HL7_NS)
    if not nodes:
        return None
    return nodes[0]

def _first_xpath_attr(elem: etree.Element, xpath_expr: str) -> Any | None:
    vals = elem.xpath(xpath_expr, namespaces=HL7_NS)
    if not vals:
        return None
    return vals[0]

def _collect_xpath_attrs(elem: etree.Element, xpath_expr: str, limit: int = 6) -> list[Any | None]:
    vals = elem.xpath(xpath_expr, namespaces=HL7_NS)
    if not vals:
        return []
    return list(vals[:limit])

def _get_statement_node(elem: etree._Element) -> Any | None:
    return _first_xpath_node(elem,
        "./hl7:entry"
        "/(hl7:act | hl7:observation | hl7:encounter | hl7:procedure | hl7:substanceAdministration | hl7:supply | hl7:organizer)"
    )

def unique_keys(elems: list[etree.Element]) -> list[tuple[Any, ...]] | None:
    keys: list[tuple[Any, ...]] = []
    for e in elems:
        key = stable_key(e)
        if key is None:
            return None
        keys.append(key)
    if len(set(keys)) != len(keys)
        return None
    return keys

def stable_key(elem: etree.Element) -> tuple[Any, ...] | None:
    """Extracts a key to consistently identify a given element across diffs."""
    # if the element has any key attributes, return a tuple of those attributes as the "key"
    items = []
    for attr in KEY_ATTRS:
        if attr in elem.attrib:
            items.append((attr, elem.attrib.get(attr)))
    if items:
        return ("@attrs", tuple(items))

    # 2. if the element has a direct templateId root
    template_id_root = _first_xpath_attr(elem, "./hl7:templateId/@root")
    if template_id_root:
        template_id_extension = _first_xpath_attr(elem, "./hl7:templateId/@extension") or ""
        return ("templateId", ("root", template_id_root), ("extension", template_id_extension))

    # 3. if the element has a direct id root
    id_root = _first_xpath_attr(elem, "./hl7:id/@root")
    if id_root:
        id_extension = _first_xpath_attr(elem, "./hl7:id/@extension") or ""
        return ("id", ("root", id_root), ("extension", id_extension))

    # 4. if the element has nested section templateId roots (limit to 8)
    section_template_id_roots = _collect_xpath_attrs(elem, ".//hl7:section/hl7:templateId/@root", 8)
    if section_template_id_roots:
        return ("nested.section.templateId.roots", tuple(sorted(section_template_id_roots)))

    # 5. if the element has a nested CDA statement node
    cda_statement = _get_statement_node(elem)
    if cda_statement is not None:
        # if the statement has a root + extension
        id_root = _first_xpath_attr(cda_statement, "./hl7:id/@root")
        id_extension = _first_xpath_attr(cda_statement, "./hl7:id/@extension")
        if id_root and id_extension:
            return ("nested.entry.statement.id", ("root", id_root), ("extension", id_extension))

        # if the statement has templateId roots
        template_id_roots = _collect_xpath_attrs(elem, ".//hl7:section/hl7:templateId/@root", 8)
        if template_id_roots:
            return ("nested.entry.statement.templateId.roots", tuple(sorted(template_id_roots)))

    # 6. if the element contains any nested id root + extension pairs anywhere
    any_id_root = _first_xpath_attr(elem, ".//hl7:id/@root")
    any_id_extension = _first_xpath_attr(elem, ".//hl7:id/@extension")
    if any_id_root and any_id_extension:
        return ("nested.any.id", ("root", any_id_root), ("extension", any_id_extension))

    # there are no reliable stable keys for this element
    return None
