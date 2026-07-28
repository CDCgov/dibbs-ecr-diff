"""CDA narrative table and row key derivation."""

from lxml import etree

from core.constants import NAMESPACES
from core.xml_utils import localname, normalize_text


def narrative_table_key(elem: etree._Element) -> tuple | None:
    """Derive a stable narrative key for a CDA narrative <table> element.

    Prefers the column header labels from <thead>; falls back to the text of
    the first cell in the first row.  Returns None for non-table elements.
    """
    if localname(elem) != "table":
        return None

    headers = elem.xpath("./hl7:thead/hl7:tr[1]/hl7:th", namespaces=NAMESPACES)
    if headers:
        labels = [normalize_text(th.text) for th in headers if normalize_text(th.text)]
        if labels:
            return ("table.headers", tuple(labels))

    first_cell = elem.xpath(
        ".//hl7:tr[1]/*[self::hl7:th or self::hl7:td][1]",
        namespaces=NAMESPACES,
    )
    if first_cell:
        text = normalize_text(first_cell[0].text)
        if text:
            return ("table.first_cell", text)

    return None


def narrative_row_key(elem: etree._Element) -> tuple | None:
    """Derive a stable narrative key for a CDA narrative <tr> element.

    Prefers the text of the first cell; falls back to all cell text joined
    with a pipe separator.  Returns None for non-tr elements.
    """
    if localname(elem) != "tr":
        return None

    first_cell = elem.xpath("./hl7:td[1] | ./hl7:th[1]", namespaces=NAMESPACES)
    if first_cell:
        text = normalize_text(first_cell[0].text)
        if text:
            return ("row.first_cell", text)

    cells = elem.xpath("./hl7:td | ./hl7:th", namespaces=NAMESPACES)
    joined = "|".join(
        normalize_text(cell.text) for cell in cells if normalize_text(cell.text)
    )
    if joined:
        return ("row.cells", joined)

    return None
