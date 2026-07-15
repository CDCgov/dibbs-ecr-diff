"""Core Difference in Docs functionality."""

from collections.abc import Iterable
from dataclasses import dataclass

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
        with measure_time(f"Execute {len(rule.xpaths)} xpaths for {rule.name}"):
            for xpath in rule.xpaths:
                vals = eval_xpath(elem, xpath)

                for val in vals:
                    nodes[val] = WatchedNode(
                        node=val, tag=str(val.tag), xpath=xpath, rule_name=rule.name
                    )
    return nodes


def nodes_in_cache(
    origin_node: etree._Element, nodes: Iterable[etree._Element], cache: NodeCache
) -> list[WatchedNode]:
    """Generic method for collecting all matched nodes from a cache."""
    matches: list[WatchedNode] = []

    for node in [origin_node, *nodes]:
        cached = cache.get(node)
        if cached is not None:
            if cached.node is not origin_node:
                cached.origin_node = origin_node
            matches.append(cached)

    return matches


def cached_ancestry(node: etree._Element, cache: NodeCache) -> list[WatchedNode]:
    """Collect node and all ancestor matches."""
    return nodes_in_cache(node, node.iterancestors(), cache)


def cached_subtree(node: etree._Element, cache: NodeCache) -> list[WatchedNode]:
    """Collect node and all descendant matches."""
    return nodes_in_cache(node, node.iterdescendants(), cache)


def diff_xml(opts: DiffingOptions, config: Configuration) -> str:
    """Returns a XML diff string."""
    diff_output = DiffOutput()
    parser = etree.XMLParser(remove_blank_text=True, huge_tree=True)

    with measure_time("Parse XML files"):
        left_tree = etree.parse(opts.file1, parser)
        right_tree = etree.parse(opts.file2, parser)

    with measure_time("Execute XPaths"):
        left_cache = build_cache(left_tree, config.rules)
        right_cache = build_cache(right_tree, config.rules)

    with measure_time("Perform diff and collect changes"):
        added, updated, deleted = collect_additions_updates_deletes(
            left_tree.getroot(), right_tree.getroot()
        )

    with measure_time("Process additions"):
        for after in added:
            if config.mode == DiffMode.WATCH_LIST:
                for cached in cached_subtree(after, right_cache):
                    diff_output.changes.append(
                        Change(
                            xpath=cached.xpath,
                            rule_name=cached.rule_name,
                            changeType=ChangeType.ADDED,
                            xml=build_standalone_xml_string(cached.effective_node),
                        )
                    )
            elif config.mode == DiffMode.IGNORE_LIST:
                if cached_ancestry(after, right_cache):
                    continue

                diff_output.changes.append(
                    Change(
                        xpath=after.getroottree().getpath(after),
                        changeType=ChangeType.ADDED,
                        xml=build_standalone_xml_string(after),
                    )
                )

    with measure_time("Process updates"):
        for [before, after] in updated:
            if config.mode == DiffMode.WATCH_LIST:
                for cached in cached_ancestry(after, right_cache):
                    diff_output.changes.append(
                        Change(
                            xpath=cached.xpath,
                            rule_name=cached.rule_name,
                            changeType=ChangeType.UPDATED,
                            xml=build_standalone_xml_string(cached.effective_node),
                        )
                    )
            elif config.mode == DiffMode.IGNORE_LIST:
                if cached_ancestry(before, left_cache) or cached_ancestry(
                    after, right_cache
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
        for before in deleted:
            if config.mode == DiffMode.WATCH_LIST:
                for cached in cached_subtree(before, left_cache):
                    diff_output.changes.append(
                        Change(
                            xpath=cached.xpath,
                            rule_name=cached.rule_name,
                            changeType=ChangeType.DELETED,
                            xml=build_standalone_xml_string(cached.effective_node),
                        )
                    )
            elif config.mode == DiffMode.IGNORE_LIST:
                if cached_ancestry(before, left_cache):
                    continue

                diff_output.changes.append(
                    Change(
                        xpath=before.getroottree().getpath(before),
                        changeType=ChangeType.DELETED,
                        xml=build_standalone_xml_string(before),
                    )
                )

    return diff_output.model_dump_json(indent=2)
