from lxml import etree
from .models import HL7_NS

KEY_ATTRS = ("ID", "id", "root", "extension", "code")

def _first_xpath_attr(elem: etree._Element, xpath_expr: str):
    vals = elem.xpath(xpath_expr, namespaces=HL7_NS)
    if not vals:
        return None
    return vals[0]

def unique_keys(elems: list[etree.Element]) -> bool:
    keys = []
    for e in elems:
        key = stable_key(e)
        if key is None:
            return None
        keys.append(key)
    if len(set(keys)) != len(keys)
        return None
    return keys

def stable_key(elem: etree.Element) -> tuple | None:
    """Extracts a key to consistently identify a given element across diffs."""
    # 1. if the element has any key attributes, return a tuple of those attributes as the "key"
    items = []
    for attr in KEY_ATTRS:
        if attr in elem.attrib:
            items.append((attr, elem.attrib.get(attr)))
    if items:
        return ("@attrs", tuple(items))

    # 2. if the element has a direct templateId root
    template_root = _first_xpath_attr(elem, "./hl7:templateId/@root")
