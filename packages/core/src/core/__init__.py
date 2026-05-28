"""Core Difference in Docs functionality."""

from typing import Any

from lxml import etree

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

XPATHS = [
    "/hl7:ClinicalDocument/hl7:component/hl7:structuredBody/hl7:component/hl7:section//hl7:value",
    # "/hl7:ClinicalDocument/hl7:component/hl7:structuredBody/hl7:component/hl7:section/hl7:text",
]


def eval_xpath(elem: etree._Element | etree._ElementTree, xpath_expr: str) -> list[Any]:
    return elem.xpath(xpath_expr, namespaces=HL7_NAMESPACE) or []


def build_watched(elem: etree._ElementTree):
    nodes = {}
    # attrs = {}

    for xpath in XPATHS:
        vals = eval_xpath(elem, xpath)

        for val in vals:
            nodes[val] = {"tag": val.tag}
            # is_attribute = getattr(val, "is_attribute", False)

            # if is_attribute:
            #     parent = val.getparent()
            #     attrs[parent] = {"name": val.attrname}
            # else:

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

    for u in updated:
        before, after = u

        if before in watched_left_nodes:
            print("this is being watched in the left tree")
        if after in watched_right_nodes:
            print("this is being watched in the right tree")

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
