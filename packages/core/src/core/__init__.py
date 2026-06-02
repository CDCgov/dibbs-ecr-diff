"""Core Difference in Docs functionality."""

from lxml import etree

from core.xml_utils import build_standalone_xml_string

from .constants import HL7_NAMESPACE
from .diff_engine import collect_additions_updates_deletes
from .models import (
    Change,
    ChangeType,
    Configuration,
    DiffingOptions,
    DiffOutput,
    RuleConfig,
)
from .performance import measure_time


def eval_xpath(
    elem: etree._Element | etree._ElementTree, xpath_expr: str
) -> list[etree._Element]:
    """Evaluate an XPath and return resulting list of elements."""
    return elem.xpath(xpath_expr, namespaces=HL7_NAMESPACE) or []


def find_watched_nodes(
    root: etree._Element, mapping: dict[etree._Element, dict[str, str]]
) -> list[tuple[etree._Element, str, str, etree._Element | None]]:
    """Collect all matching nodes from watch/ignore mapping.

    This traverses the given `root` etree._Element
    and all descendants in document order (root -> leaf)
    and appends them to the matches list.

    In the case that the matching node is a descendant, the root el
    is also added to the end of the tuple.
    """
    matches = []

    if root in mapping:
        xpath = mapping[root]["xpath"]
        rule_name = mapping[root]["rule_name"]
        matches.append((root, xpath, rule_name, None))

    for descendant in root.iterdescendants():
        if descendant in mapping:
            xpath = mapping[descendant]["xpath"]
            rule_name = mapping[descendant]["rule_name"]
            matches.append((descendant, xpath, rule_name, root))

    return matches


def build_watched(
    elem: etree._ElementTree, rules: list[RuleConfig]
) -> dict[etree._Element, dict[str, str]]:
    """Execute XPaths against element to build mappings."""
    nodes: dict[etree._Element, dict[str, str]] = {}

    for rule in rules:
        for xpath in rule.xpaths:
            vals = eval_xpath(elem, xpath)
            for val in vals:
                nodes[val] = {
                    "tag": str(val.tag),
                    "xpath": xpath,
                    "rule_name": rule.name,
                }
    return nodes


def diff_xml(opts: DiffingOptions, config: Configuration) -> str:
    """Returns a XML diff string."""
    diff_output = DiffOutput()
    parser = etree.XMLParser(remove_blank_text=True, huge_tree=True)

    with measure_time("Parse XML files"):
        tree_left = etree.parse(opts.file1, parser)
        tree_right = etree.parse(opts.file2, parser)

    with measure_time("Execute XPaths"):
        watched_left_nodes = build_watched(tree_left, config.rules)
        watched_right_nodes = build_watched(tree_right, config.rules)

    with measure_time("Perform diff and collect changes"):
        added, updated, deleted = collect_additions_updates_deletes(
            tree_left.getroot(), tree_right.getroot()
        )

    with measure_time("Process additions"):
        for after in added:
            if config.mode == "WATCH":
                for node, xpath, rule_name, ancestor in find_watched_nodes(
                    after, watched_right_nodes
                ):
                    diff_output.changes.append(
                        Change(
                            xpath=xpath,
                            rule_name=rule_name,
                            changeType=ChangeType.ADDED,
                            xml=build_standalone_xml_string(node),
                            ancestor_xml=build_standalone_xml_string(ancestor)
                            if ancestor is not None
                            else None,
                        )
                    )
            elif config.mode == "IGNORE":
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

    with measure_time("Process updates"):
        for [before, after] in updated:
            if config.mode == "WATCH":
                for node, xpath, rule_name, ancestor in find_watched_nodes(
                    after, watched_right_nodes
                ):
                    # the before node should be in the watched left tree
                    # TODO: is this necessary? probably not
                    before_node = find_watched_nodes(before, watched_left_nodes)
                    if before_node is None:
                        continue

                    diff_output.changes.append(
                        Change(
                            xpath=xpath,
                            rule_name=rule_name,
                            changeType=ChangeType.UPDATED,
                            xml=build_standalone_xml_string(node),
                            ancestor_xml=build_standalone_xml_string(ancestor)
                            if ancestor is not None
                            else None,
                        )
                    )
            elif config.mode == "IGNORE":
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

    with measure_time("Process deletions"):
        for before in deleted:
            if config.mode == "WATCH":
                for node, xpath, rule_name, ancestor in find_watched_nodes(
                    before, watched_left_nodes
                ):
                    diff_output.changes.append(
                        Change(
                            xpath=xpath,
                            rule_name=rule_name,
                            changeType=ChangeType.DELETED,
                            xml=build_standalone_xml_string(node),
                            ancestor_xml=build_standalone_xml_string(ancestor)
                            if ancestor is not None
                            else None,
                        )
                    )
            elif config.mode == "IGNORE":
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
