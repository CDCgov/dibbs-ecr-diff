"""Core Difference in Docs functionality."""

from enum import StrEnum

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


# MODE = "WATCH"
MODE = "IGNORE"
# XPATHS = [
#     "/hl7:ClinicalDocument/hl7:component/hl7:structuredBody/hl7:component/hl7:section[hl7:templateId/@root='2.16.840.1.113883.10.20.22.2.5.1']/hl7:entry/hl7:act/hl7:entryRelationship/hl7:observation/hl7:value",
#     "//hl7:observation[@moodCode = 'EVN']/hl7:value/@displayName",
# ]

XPATHS = [
    "/hl7:ClinicalDocument/hl7:component/hl7:structuredBody/hl7:component/hl7:section//hl7:value",
    "/hl7:ClinicalDocument/hl7:component/hl7:structuredBody/hl7:component/hl7:section/hl7:entry",
    # "/hl7:ClinicalDocument/hl7:component/hl7:structuredBody/hl7:component/hl7:section/hl7:text",
]


def eval_xpath(
    elem: etree._Element | etree._ElementTree, xpath_expr: str
) -> list[etree._Element]:
    return elem.xpath(xpath_expr, namespaces=HL7_NAMESPACE) or []


def find_watched_nodes(
    root: etree._Element, mapping: dict[etree._Element, dict[str, str]]
) -> list[tuple[etree._Element, str, etree._Element | None]]:
    matches = []
    """
    Collect all matching nodes from watch/ignore mapping.

    This traverses the given `root` etree._Element
    and all descendants in document order (root -> leaf)
    and appends them to the matches list.

    In the case that the matching node is a descendant, the root el
    is also added to the end of the tuple.
    """
    if root in mapping:
        matches.append((root, mapping[root]["xpath"], None))
    for descendant in root.iterdescendants():
        if descendant in mapping:
            matches.append((descendant, mapping[descendant]["xpath"], root))
    return matches


def build_watched(elem: etree._ElementTree) -> dict[etree._Element, dict[str, str]]:
    nodes: dict[etree._Element, dict[str, str]] = {}
    for xpath in XPATHS:
        vals = eval_xpath(elem, xpath)
        for val in vals:
            nodes[val] = {"tag": str(val.tag), "xpath": xpath}
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
        if MODE == "WATCH":
            for node, xpath, ancestor in find_watched_nodes(after, watched_right_nodes):
                diff_output.changes.append(
                    Change(
                        xpath=xpath,
                        changeType=ChangeType.ADDED,
                        xml=build_standalone_xml_string(node),
                        ancestor_xml=build_standalone_xml_string(ancestor)
                        if ancestor is not None
                        else None,
                    )
                )
        elif MODE == "IGNORE":
            if after in watched_right_nodes:
                continue

            diff_output.changes.append(
                Change(
                    xpath=after.getroottree().getpath(after),
                    changeType=ChangeType.ADDED,
                    xml=build_standalone_xml_string(after),
                    ancestor_xml=None,
                )
            )

    for [before, after] in updated:
        if MODE == "WATCH":
            for node, xpath, ancestor in find_watched_nodes(after, watched_right_nodes):
                # the before node should be in the watched left tree
                # TODO: is this necessary? probably not
                before_node = find_watched_nodes(before, watched_left_nodes)
                if before_node is None:
                    continue

                diff_output.changes.append(
                    Change(
                        xpath=xpath,
                        changeType=ChangeType.UPDATED,
                        xml=build_standalone_xml_string(node),
                        ancestor_xml=build_standalone_xml_string(ancestor)
                        if ancestor is not None
                        else None,
                    )
                )
        elif MODE == "IGNORE":
            if before in watched_left_nodes or after in watched_right_nodes:
                continue

            diff_output.changes.append(
                Change(
                    xpath=after.getroottree().getpath(after),
                    changeType=ChangeType.UPDATED,
                    xml=build_standalone_xml_string(after),
                    ancestor_xml=None,
                )
            )

    for before in deleted:
        if MODE == "WATCH":
            for node, xpath, ancestor in find_watched_nodes(before, watched_left_nodes):
                diff_output.changes.append(
                    Change(
                        xpath=xpath,
                        changeType=ChangeType.DELETED,
                        xml=build_standalone_xml_string(node),
                        ancestor_xml=build_standalone_xml_string(ancestor)
                        if ancestor is not None
                        else None,
                    )
                )
        elif MODE == "IGNORE":
            if before in watched_left_nodes:
                continue

            diff_output.changes.append(
                Change(
                    xpath=before.getroottree().getpath(before),
                    changeType=ChangeType.DELETED,
                    xml=build_standalone_xml_string(before),
                    ancestor_xml=None,
                )
            )

    return diff_output.model_dump_json(indent=2)
