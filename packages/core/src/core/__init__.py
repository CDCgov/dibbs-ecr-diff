"""Core Difference in Docs functionality."""

from typing import Any

from lxml import etree

from core.xml_utils import build_standalone_xml_string

from .constants import HL7_NAMESPACE
from .diff_engine import collect_additions_updates_deletes
from .models import DiffingOptions

# from .xml_utils import build_standalone_xml_string

MODE = "WATCH"
# MODE = "IGNORE"
# XPATHS = [
#     "/hl7:ClinicalDocument/hl7:component/hl7:structuredBody/hl7:component/hl7:section[hl7:templateId/@root='2.16.840.1.113883.10.20.22.2.5.1']/hl7:entry/hl7:act/hl7:entryRelationship/hl7:observation/hl7:value",
#     "//hl7:observation[@moodCode = 'EVN']/hl7:value/@displayName",
# ]

# what if i watched for hl7:value, and it *is* added, but deeply nested somewhere?

XPATHS = [
    "/hl7:ClinicalDocument/hl7:component/hl7:structuredBody/hl7:component/hl7:section//hl7:value",
    # "/hl7:ClinicalDocument/hl7:component/hl7:structuredBody/hl7:component/hl7:section//hl7:value",
    # "/hl7:ClinicalDocument/hl7:component/hl7:structuredBody/hl7:component/hl7:section/hl7:text",
]


def eval_xpath(elem: etree._Element | etree._ElementTree, xpath_expr: str) -> list[Any]:
    return elem.xpath(xpath_expr, namespaces=HL7_NAMESPACE) or []


def node_or_child_in_map(
    elem: etree._Element, list: dict[etree._Element, dict[str, str]]
) -> etree._Element | None:
    if elem in list:
        return elem
    for x in elem.iterdescendants():
        if x in list:
            return x
    return None


def build_watched(elem: etree._ElementTree) -> dict[etree._Element, dict[str, str]]:
    nodes: dict[etree._Element, dict[str, str]] = {}
    for xpath in XPATHS:
        vals = eval_xpath(elem, xpath)
        for val in vals:
            nodes[val] = {"tag": val.tag}
    return nodes


def diff_xml(opts: DiffingOptions) -> str:
    """Returns a XML diff string."""
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

    for x in added:
        added_node = node_or_child_in_map(x, watched_right_nodes)
        if isinstance(added_node, etree._Element):
            print("a watched xpath has been added")
            # TODO: maybe good to include the *actual* added parent element
            print(build_standalone_xml_string(added_node))
            print(tree_right.getelementpath(added_node))

    # for deleted_node in deleted:
    #     if node_or_child_in_map(deleted_node, watched_left_nodes):
    #         print("yes that node was in the first tree")
    #         if not node_or_child_in_map(deleted_node, watched_right_nodes):
    #             print("and is no longer in the right tree")
    #         print(build_standalone_xml_string(deleted_node))

    # for u in updated:
    #     before, after = u

    #     if before in watched_left_nodes:
    #         print("this is being watched in the left tree")
    #     if after in watched_right_nodes:
    #         print("this is being watched in the right tree")

    # if left in watched_left_attrs:
    #     print("its watched")
    #     print(build_standalone_xml_string(left))
    # if right in watched_right_attrs:
    #     print("its watched (right)")
    #     print(build_standalone_xml_string(left))

    # for w in wraps:
    #     change_type, after_node, before_node_or_None = w
    #     print(build_standalone_xml_string(after_node))
    #     print("---")

    # for d in deletes:
    #     parent_in_after, reference_sibling_or_None, placement, deleted_before_node = d
    #     # print(build_standalone_xml_string(reference_sibling_or_None))

    return "hello world"
