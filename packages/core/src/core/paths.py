"""
core/paths.py

Human-readable xmlPath and machine-readable xPath generation.

Both path types are written into changes.json alongside each change entry
to help consumers locate the changed element in the document.
"""

from typing import Dict, List, Optional

from lxml import etree

from core.cda_identity import (
    StableKey,
    _direct_template_id_identities,
    narrative_row_key,
    narrative_table_key,
    stable_key,
)
from core.constants import HL7_NS, HL7_PREFIX
from core.xml_utils import _xpath_first_attribute_value, localname


def _pfx(tag: str) -> str:
    """Prefixed tag for generated XPath output, e.g. 'id' → 'hl7:id'."""
    return f"{HL7_PREFIX}:{tag}"


# ---------------------------------------------------------------------------
# Human-readable xmlPath
# ---------------------------------------------------------------------------


def _stable_key_to_label(stable_key_tuple: Optional[StableKey]) -> Optional[str]:
    """Convert a stable_key tuple into a concise human-readable bracket label."""
    if stable_key_tuple is None:
        return None
    kind = stable_key_tuple[0]

    def _template_identities_to_label(template_identities: tuple) -> str | None:
        parts = []
        for template_id_identity in template_identities:
            part = f"root={template_id_identity.root}"
            if template_id_identity.extension:
                part += f";extension={template_id_identity.extension}"
            parts.append(part)

        if not parts:
            return None

        prefix = "template" if len(parts) == 1 else "templates"
        return f"{prefix}:{'|'.join(parts)}"

    def _root_extension_identities_to_label(
        prefix: str,
        root_extension_identities: tuple,
    ) -> str | None:
        parts = []
        for root_extension_identity in root_extension_identities:
            part = f"root={root_extension_identity.root}"
            if root_extension_identity.extension:
                part += f";extension={root_extension_identity.extension}"
            parts.append(part)

        if not parts:
            return None

        return f"{prefix}:{'|'.join(parts)}"

    if kind == "narr_table":
        inner = stable_key_tuple[1]
        if inner and inner[0] == "table.headers":
            return f'headers="{"|".join(inner[1])}"'
        if inner and inner[0] == "table.first_cell":
            return f'first="{inner[1]}"'

    if kind == "narr_row":
        inner = stable_key_tuple[1]
        if inner and inner[0] == "row.first_cell":
            return f'first="{inner[1]}"'
        if inner and inner[0] == "row.cells":
            return f'cells="{inner[1]}"'

    if kind in (
        "templateIds",
        "nested.entry.statement.templateIds",
        "nested.section.templateIds",
    ):
        return _template_identities_to_label(stable_key_tuple[1])

    if kind in ("ids", "nested.entry.statement.ids", "nested.section.ids"):
        return _root_extension_identities_to_label("ids", stable_key_tuple[1])

    if kind == "@root":
        root_extension_identity = stable_key_tuple[1]
        label = f"root={root_extension_identity.root}"
        if root_extension_identity.extension:
            label += f";extension={root_extension_identity.extension}"
        return f"id:{label}"

    if kind == "@code":
        return "code:" + ";".join(
            f"{part[0]}={part[1]}" for part in stable_key_tuple[1] if part[1]
        )

    if kind in ("@attrs", "nested.entry.statement.@attrs"):
        return "attrs:" + ";".join(f"{key}={val}" for key, val in stable_key_tuple[1])

    return None


def stable_xml_path(
    elem: etree._Element,
    anchor: str = "ClinicalDocument",
) -> str:
    """
    Return a stable, human-readable path string for elem.

    Uses meaningful bracket labels derived from stable_key / narrative keys
    where available; falls back to positional [:N] notation otherwise.
    Stops ascending at the element whose local name matches `anchor`.
    """
    parts = []
    current = elem

    while current is not None:
        if not isinstance(current.tag, str):
            current = current.getparent()
            continue

        local = localname(current)

        if local == "table":
            table_key = narrative_table_key(current)
            elem_key = ("narr_table", table_key) if table_key else None
        elif local == "tr":
            row_key = narrative_row_key(current)
            elem_key = ("narr_row", row_key) if row_key else None
        else:
            elem_key = stable_key(current)

        label = _stable_key_to_label(elem_key)
        parent = current.getparent()

        if parent is None:
            position = 1
        else:
            siblings = [
                child
                for child in parent
                if isinstance(child.tag, str) and localname(child) == local
            ]
            position = (siblings.index(current) + 1) if current in siblings else 1

        parts.append(f"{local}[{label}]" if label else f"{local}[:{position}]")

        if local == anchor:
            break
        current = parent

    return "/" + "/".join(reversed(parts))


# ---------------------------------------------------------------------------
# Machine-readable xPath (hl7: prefix, stable predicates)
# ---------------------------------------------------------------------------


def _xpath_literal(value: str) -> str:
    """
    Wrap value in XPath-safe quotes.  Falls back to concat() when value
    contains both single and double quotes.
    """
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    concat_parts = []
    for chunk in value.split("'"):
        if chunk:
            concat_parts.append(f"'{chunk}'")
        concat_parts.append('"\'"')
    if concat_parts and concat_parts[-1] == '"\'"':
        concat_parts.pop()
    return "concat(" + ",".join(concat_parts) + ")"


def _direct_template_id_predicates(node: etree._Element) -> list[str]:
    """Return XPath predicates for every direct templateId identity on node."""
    predicates = []
    for template_id_identity in _direct_template_id_identities(node):
        conditions = [
            f"@root={_xpath_literal(template_id_identity.root)}",
        ]
        if template_id_identity.extension:
            conditions.append(
                f"@extension={_xpath_literal(template_id_identity.extension)}"
            )
        else:
            conditions.append("(not(@extension) or @extension='')")

        predicates.append(f"{_pfx('templateId')}[{' and '.join(conditions)}]")

    return predicates


def _append_xpath_predicate(predicates: List[str], predicate: str) -> None:
    """Append predicate unless an earlier identity helper already produced it."""
    if predicate not in predicates:
        predicates.append(predicate)


def _direct_attribute_stable_key_predicates(
    stable_key_tuple: Optional[StableKey],
) -> list[str]:
    """Return XPath predicates for direct attribute stable-key variants."""
    if stable_key_tuple is None:
        return []

    kind = stable_key_tuple[0]
    if kind == "@root":
        root_extension_identity = stable_key_tuple[1]
        predicates = [f"@root={_xpath_literal(root_extension_identity.root)}"]
        if root_extension_identity.extension:
            predicates.append(
                f"@extension={_xpath_literal(root_extension_identity.extension)}"
            )
        return predicates

    if kind not in ("@attrs", "@code"):
        return []

    return [
        f"@{attr}={_xpath_literal(value)}"
        for attr, value in stable_key_tuple[1]
        if value
    ]


def _position_among_siblings(node: etree._Element) -> int:
    """Return the 1-based position of node among siblings with the same local name."""
    parent = node.getparent()
    if parent is None:
        return 1
    local = localname(node)
    siblings = [
        child
        for child in parent
        if isinstance(child.tag, str) and localname(child) == local
    ]
    try:
        return siblings.index(node) + 1
    except ValueError:
        return 1


def _effective_time_predicates(node: etree._Element) -> Dict[str, str]:
    """
    Return a dict of available effectiveTime component values for node.
    Keys: "value", "low", "high", "center", "period_value", "period_unit".
    """
    result: Dict[str, str] = {}

    point_value = _xpath_first_attribute_value(node, "./hl7:effectiveTime/@value")
    if point_value:
        result["value"] = point_value
        return result

    low_value = _xpath_first_attribute_value(node, "./hl7:effectiveTime/hl7:low/@value")
    high_value = _xpath_first_attribute_value(
        node, "./hl7:effectiveTime/hl7:high/@value"
    )
    if low_value or high_value:
        result["low"] = low_value or ""
        result["high"] = high_value or ""
        return result

    center_value = _xpath_first_attribute_value(
        node, "./hl7:effectiveTime/hl7:center/@value"
    )
    if center_value:
        result["center"] = center_value
        return result

    period_value = _xpath_first_attribute_value(
        node, "./hl7:effectiveTime/hl7:period/@value"
    )
    period_unit = _xpath_first_attribute_value(
        node, "./hl7:effectiveTime/hl7:period/@unit"
    )
    if period_value or period_unit:
        result["period_value"] = period_value or ""
        result["period_unit"] = period_unit or ""

    return result


def xpath_with_predicates(
    elem: etree._Element,
    anchor: str = "ClinicalDocument",
) -> str:
    """
    Return a machine-readable absolute XPath for elem using hl7: namespace prefix.

    Stable predicates (id, templateId, code, effectiveTime) are used where
    available; positional [N] predicates are used as a fallback.
    Stops ascending at the element whose local name matches `anchor`.
    """
    steps: List[str] = []
    current = elem

    while current is not None:
        if not isinstance(current.tag, str):
            current = current.getparent()
            continue

        local = localname(current)
        qname = etree.QName(current.tag)
        tag_step = _pfx(local) if qname.namespace == HL7_NS else local
        predicates: List[str] = []

        if local == "table":
            table_key = narrative_table_key(current)
            if table_key and table_key[0] == "table.headers":
                for header_index, header_text in enumerate(
                    list(table_key[1])[:4], start=1
                ):
                    predicates.append(
                        f"{_pfx('thead')}/{_pfx('tr')}[1]/{_pfx('th')}[{header_index}]"
                        f"[normalize-space()={_xpath_literal(header_text)}]"
                    )
            elif table_key and table_key[0] == "table.first_cell":
                predicates.append(
                    f".//{_pfx('tr')}[1]/*[self::{_pfx('th')} or"
                    f" self::{_pfx('td')}][1]"
                    f"[normalize-space()={_xpath_literal(table_key[1])}]"
                )

        elif local == "tr":
            row_key = narrative_row_key(current)
            if row_key and row_key[0] == "row.first_cell":
                predicates.append(
                    f"{_pfx('td')}[1][normalize-space()={_xpath_literal(row_key[1])}]"
                    f" or {_pfx('th')}[1][normalize-space()={_xpath_literal(row_key[1])}]"
                )
            elif row_key and row_key[0] == "row.cells":
                predicates.append(
                    f"contains(normalize-space(string(.)),"
                    f" {_xpath_literal(row_key[1][:50])})"
                )

        else:
            elem_key = stable_key(current)
            for predicate in _direct_attribute_stable_key_predicates(elem_key):
                _append_xpath_predicate(predicates, predicate)

            id_root = _xpath_first_attribute_value(current, "./hl7:id/@root")
            id_ext = _xpath_first_attribute_value(current, "./hl7:id/@extension")
            if id_root and id_ext:
                predicates.append(
                    f"{_pfx('id')}[@root={_xpath_literal(id_root)}"
                    f" and @extension={_xpath_literal(id_ext)}]"
                )
            elif id_root:
                predicates.append(f"{_pfx('id')}[@root={_xpath_literal(id_root)}]")

            predicates.extend(_direct_template_id_predicates(current))

            code_value = _xpath_first_attribute_value(current, "./hl7:code/@code")
            code_system = _xpath_first_attribute_value(
                current, "./hl7:code/@codeSystem"
            )
            if code_value and code_system:
                predicates.append(
                    f"{_pfx('code')}[@code={_xpath_literal(code_value)}"
                    f" and @codeSystem={_xpath_literal(code_system)}]"
                )

            effective_time = _effective_time_predicates(current)
            if effective_time:
                if "value" in effective_time:
                    predicates.append(
                        f"{_pfx('effectiveTime')}[@value={_xpath_literal(effective_time['value'])}]"
                    )
                elif "low" in effective_time or "high" in effective_time:
                    time_conditions = []
                    if effective_time.get("low"):
                        time_conditions.append(
                            f"{_pfx('effectiveTime')}/{_pfx('low')}"
                            f"[@value={_xpath_literal(effective_time['low'])}]"
                        )
                    if effective_time.get("high"):
                        time_conditions.append(
                            f"{_pfx('effectiveTime')}/{_pfx('high')}"
                            f"[@value={_xpath_literal(effective_time['high'])}]"
                        )
                    if time_conditions:
                        predicates.append(" and ".join(time_conditions))
                elif "center" in effective_time:
                    predicates.append(
                        f"{_pfx('effectiveTime')}/{_pfx('center')}"
                        f"[@value={_xpath_literal(effective_time['center'])}]"
                    )
                elif (
                    "period_value" in effective_time or "period_unit" in effective_time
                ):
                    period_conditions = []
                    if effective_time.get("period_value"):
                        period_conditions.append(
                            f"{_pfx('effectiveTime')}/{_pfx('period')}"
                            f"[@value={_xpath_literal(effective_time['period_value'])}]"
                        )
                    if effective_time.get("period_unit"):
                        period_conditions.append(
                            f"{_pfx('effectiveTime')}/{_pfx('period')}"
                            f"[@unit={_xpath_literal(effective_time['period_unit'])}]"
                        )
                    if period_conditions:
                        predicates.append(" and ".join(period_conditions))

            root_value = current.get("root")
            if root_value:
                _append_xpath_predicate(
                    predicates,
                    f"@root={_xpath_literal(root_value)}",
                )

            extension_value = current.get("extension")
            if extension_value:
                _append_xpath_predicate(
                    predicates,
                    f"@extension={_xpath_literal(extension_value)}",
                )

        step = tag_step
        step += (
            ("[" + " and ".join(predicates) + "]")
            if predicates
            else f"[{_position_among_siblings(current)}]"
        )
        steps.append(step)

        if local == anchor:
            break
        current = current.getparent()

    return "/" + "/".join(reversed(steps))
