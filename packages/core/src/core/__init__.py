"""Core Difference in Docs functionality."""

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from lxml import etree

from core.xml_utils import build_standalone_xml_string

from .constants import NAMESPACES
from .diff_collector import collect_additions_updates_deletes
from .models import (
    Change,
    ChangeType,
    Configuration,
    DiffingOptions,
    DiffMode,
    DiffOutput,
    RuleConfig,
)
from .performance import measure_time


@dataclass()
class WatchedNode:
    """Metadata for watched/ignored node cache."""

    node: etree._Element
    tag: str
    xpath: str
    rule_id: UUID
    rule_name: str
    origin_node: etree._Element | None = None

    @property
    def effective_node(self) -> etree._Element:
        """Return effective node. Used when an ancestor/descendant is cached."""
        return self.origin_node if self.origin_node is not None else self.node


"""Used to cache nodes from evaluated rule XPaths."""
type NodeCache = dict[etree._Element, WatchedNode]


def eval_xpath(
    elem: etree._Element | etree._ElementTree, xpath_expr: str
) -> list[etree._Element]:
    """Evaluate an XPath and return resulting list of elements."""
    return elem.xpath(xpath_expr, namespaces=NAMESPACES) or []


def build_cache(elem: etree._ElementTree, rules: list[RuleConfig]) -> NodeCache:
    """Execute XPaths against element to build node cache."""
    nodes: NodeCache = {}

    for rule in rules:
        with measure_time(f"Execute {len(rule.xpaths)} xpaths for {rule.displayName}"):
            for xpath in rule.xpaths:
                vals = eval_xpath(elem, xpath)

                for val in vals:
                    nodes[val] = WatchedNode(
                        node=val,
                        tag=str(val.tag),
                        xpath=xpath,
                        rule_id=rule.id,
                        rule_name=rule.displayName,
                    )
    return nodes

def diff_xml(opts: DiffingOptions, config: Configuration) -> str:
    """Returns a XML diff string."""
    diff_output = DiffOutput()
    parser = etree.XMLParser(remove_blank_text=True, huge_tree=True)

    with measure_time("Parse XML files"):
        left_tree = etree.parse(opts.file1, parser)
        right_tree = etree.parse(opts.file2, parser)

    with measure_time("Execute XPaths"):
        left_elements_to_watch_cache = build_cache(left_tree, config.rules)
        right_elements_to_watch_cache = build_cache(right_tree, config.rules)

    with measure_time("Perform diff and collect changes"):
        added, updated, deleted = collect_additions_updates_deletes(
            left_tree.getroot(), right_tree.getroot()
        )

    def process_changes(changes: list[etree._Element], changeType: ChangeType,
                        watched_node_cache: NodeCache):
        for change in changes:
            watched_node_match = watched_node_cache.get(change)
            if config.mode == DiffMode.WATCH_LIST and watched_node_match:
                diff_output.changes.append(
                    Change(
                        xpath=watched_node_match.xpath,
                        rule_name=watched_node_match.rule_name,
                        changeType=changeType,
                        xml=build_standalone_xml_string(watched_node_match.effective_node),
                    )
                )
            elif config.mode == DiffMode.IGNORE_LIST and not watched_node_match:
                diff_output.changes.append(
                    Change(
                        xpath=change.getroottree().getpath(change),
                        changeType=changeType,
                        xml=build_standalone_xml_string(change),
                    )
                )
                
    with measure_time("Process changes"):
        process_changes(added, ChangeType.ADDED, right_elements_to_watch_cache)
        process_changes([after for _, after in updated], ChangeType.UPDATED, right_elements_to_watch_cache)
        process_changes(deleted, ChangeType.DELETED, left_elements_to_watch_cache)

    return diff_output.model_dump_json(indent=2)
