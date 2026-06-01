"""Core Difference in Docs functionality."""

import json
from enum import StrEnum
from typing import Any, NamedTuple

from lxml import etree
from pydantic import BaseModel

from core.xml_utils import build_standalone_xml_string

from .constants import HL7_NAMESPACE
from .diff_engine import collect_additions_updates_deletes
from .models import DiffingOptions


class ChangeType(StrEnum):
    ADDED = "ADDED"
    DELETED = "DELETED"
    UPDATED = "UPDATED"


class Change(BaseModel):
    xpath: str
    changeType: ChangeType
    xml: str
    ancestor_xml: str | None


class DiffOutput(BaseModel):
    changes: list[Change] = []


class MapMatch(NamedTuple):
    """Match found elements from diff to watch/ignore lists."""

    xpath: str | None
    node: etree._Element | None
    ancestor: etree._Element | None = None


MODE = "WATCH"
# MODE = "IGNORE"
# XPATHS = [
#     "/hl7:ClinicalDocument/hl7:component/hl7:structuredBody/hl7:component/hl7:section[hl7:templateId/@root='2.16.840.1.113883.10.20.22.2.5.1']/hl7:entry/hl7:act/hl7:entryRelationship/hl7:observation/hl7:value",
#     "//hl7:observation[@moodCode = 'EVN']/hl7:value/@displayName",
# ]

XPATHS = [
    "/hl7:ClinicalDocument/hl7:component/hl7:structuredBody/hl7:component/hl7:section//hl7:value",
    # "/hl7:ClinicalDocument/hl7:component/hl7:structuredBody/hl7:component/hl7:section//hl7:value",
    # "/hl7:ClinicalDocument/hl7:component/hl7:structuredBody/hl7:component/hl7:section/hl7:text",
]


def eval_xpath(elem: etree._Element | etree._ElementTree, xpath_expr: str) -> list[Any]:
    return elem.xpath(xpath_expr, namespaces=HL7_NAMESPACE) or []


# TODO: might make more sense to return this as part of the diff
def node_or_child_in_map(
    elem: etree._Element, mapping: dict[etree._Element, dict[str, str]]
) -> MapMatch:
    if elem in mapping:
        return MapMatch(xpath=mapping[elem]["xpath"], node=elem)
    for x in elem.iterdescendants():
        if x in mapping:
            return MapMatch(xpath=mapping[x]["xpath"], node=x, ancestor=elem)
    return MapMatch(xpath=None, node=None)


def build_watched(elem: etree._ElementTree) -> dict[etree._Element, dict[str, str]]:
    nodes: dict[etree._Element, dict[str, str]] = {}
    for xpath in XPATHS:
        vals = eval_xpath(elem, xpath)
        for val in vals:
            nodes[val] = {"tag": val.tag, "xpath": xpath}
    return nodes


def diff_xml(opts: DiffingOptions) -> str:
    """Returns a XML diff string."""
    diff_output = DiffOutput()
    parser = etree.XMLParser(remove_blank_text=True, huge_tree=True)

    # parse xml files
    tree_left = etree.parse(opts.file1, parser)
    tree_right = etree.parse(opts.file2, parser)

    # execute xpath + get watched nodes
    watched_left_nodes = build_watched(tree_left)
    watched_right_nodes = build_watched(tree_right)

    added, updated, deleted = collect_additions_updates_deletes(
        tree_left.getroot(), tree_right.getroot()
    )

    for after in added:
        xpath, node, ancestor = node_or_child_in_map(after, watched_right_nodes)
        if isinstance(node, etree._Element):
            diff_output.changes.append(
                Change(
                    xpath=xpath or "",
                    changeType=ChangeType.ADDED,
                    xml=build_standalone_xml_string(node),
                    ancestor_xml=build_standalone_xml_string(ancestor)
                    if ancestor
                    else None,
                )
            )

    for [before, after] in updated:
        xpath, left_node, left_ancestor = node_or_child_in_map(
            before, watched_left_nodes
        )

        _xpath, right_node, right_ancestor = node_or_child_in_map(
            after, watched_right_nodes
        )

        if left_node is not None and right_node is not None:
            diff_output.changes.append(
                Change(
                    xpath=xpath or "",
                    changeType=ChangeType.UPDATED,
                    xml=build_standalone_xml_string(right_node),
                    ancestor_xml=build_standalone_xml_string(right_ancestor)
                    if right_ancestor
                    else None,
                )
            )

    for after in deleted:
        xpath, node, ancestor = node_or_child_in_map(after, watched_right_nodes)
        if isinstance(node, etree._Element):
            diff_output.changes.append(
                Change(
                    xpath=xpath or "",
                    changeType=ChangeType.DELETED,
                    xml=build_standalone_xml_string(node),
                    ancestor_xml=build_standalone_xml_string(ancestor)
                    if ancestor
                    else None,
                )
            )

    output = diff_output.model_dump_json(indent=2)
    print(output)
    return output
