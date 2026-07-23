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


def nodes_in_cache(
    origin_node: etree._Element, nodes: Iterable[etree._Element], cache: NodeCache
) -> list[WatchedNode]:
    """Generic method for collecting all matched nodes from a cache."""
    matches: list[WatchedNode] = []

    for node in [origin_node, *nodes]:
        cache_match = cache.get(node)
        if cache_match is not None:
            if node is not origin_node:
                cache_match.origin_node = origin_node
            matches.append(cache_match)

    return matches


def cached_ancestry(node: etree._Element, cache: NodeCache) -> list[WatchedNode]:
    """Collect node and all ancestor matches."""
    return nodes_in_cache(node, node.iterancestors(), cache)


def cached_subtree(node: etree._Element, cache: NodeCache) -> list[WatchedNode]:
    """Collect node and all descendant matches."""
    return nodes_in_cache(node, node.iterdescendants(), cache)


def unique_rule_matches(matches: Iterable[WatchedNode]) -> list[WatchedNode]:
    """Return the first watched-node match for each rule.

    Callers check the changed node first, followed by its ancestors for updates or
    its descendants for additions and deletions. Keeping the first match therefore
    prefers the changed node when selected while preventing a broad XPath from
    emitting the same rule multiple times for one change.
    """
    first_match_by_rule: dict[UUID, WatchedNode] = {}

    for match in matches:
        if match.rule_id not in first_match_by_rule:
            first_match_by_rule[match.rule_id] = match

    return list(first_match_by_rule.values())


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

    with measure_time("Process additions"):
        for added_element in added:
            if config.mode == DiffMode.WATCH_LIST:
                for actionable_added_element in unique_rule_matches(
                    cached_subtree(added_element, right_elements_to_watch_cache)
                ):
                    diff_output.changes.append(
                        Change(
                            xpath=actionable_added_element.xpath,
                            rule_name=actionable_added_element.rule_name,
                            changeType=ChangeType.ADDED,
                            xml=build_standalone_xml_string(actionable_added_element.effective_node),
                        )
                    )
            elif config.mode == DiffMode.IGNORE_LIST:
                if cached_ancestry(added_element, right_elements_to_watch_cache):
                    continue

                diff_output.changes.append(
                    Change(
                        xpath=added_element.getroottree().getpath(added_element),
                        changeType=ChangeType.ADDED,
                        xml=build_standalone_xml_string(added_element),
                    )
                )

    with measure_time("Process updates"):
        for [before, after] in updated:
            if config.mode == DiffMode.WATCH_LIST:
                for actionable_updated_element in unique_rule_matches(
                    cached_ancestry(after, right_elements_to_watch_cache)
                ):
                    diff_output.changes.append(
                        Change(
                            xpath=actionable_updated_element.xpath,
                            rule_name=actionable_updated_element.rule_name,
                            changeType=ChangeType.UPDATED,
                            xml=build_standalone_xml_string(actionable_updated_element.effective_node),
                        )
                    )
            elif config.mode == DiffMode.IGNORE_LIST:
                if cached_ancestry(before, left_elements_to_watch_cache) or cached_ancestry(
                        after, right_elements_to_watch_cache
                ):
                    continue

                diff_output.changes.append(
                    Change(
                        xpath=after.getroottree().getpath(after),
                        changeType=ChangeType.UPDATED,
                        xml=build_standalone_xml_string(after),
                    )
                )

    with measure_time("Process deletions"):
        for deleted_element in deleted:
            if config.mode == DiffMode.WATCH_LIST:
                for actionable_deleted_element in unique_rule_matches(
                    cached_subtree(deleted_element, left_elements_to_watch_cache)
                ):
                    diff_output.changes.append(
                        Change(
                            xpath=actionable_deleted_element.xpath,
                            rule_name=actionable_deleted_element.rule_name,
                            changeType=ChangeType.DELETED,
                            xml=build_standalone_xml_string(
                                actionable_deleted_element.effective_node),
                        )
                    )
            elif config.mode == DiffMode.IGNORE_LIST:
                if cached_ancestry(deleted_element, left_elements_to_watch_cache):
                    continue

                diff_output.changes.append(
                    Change(
                        xpath=deleted_element.getroottree().getpath(deleted_element),
                        changeType=ChangeType.DELETED,
                        xml=build_standalone_xml_string(deleted_element),
                    )
                )

    return diff_output.model_dump_json(indent=2)
