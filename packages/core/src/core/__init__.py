"""Core Difference in Docs functionality."""

from collections.abc import Iterable
from dataclasses import dataclass

from lxml import etree

from core.xml_utils import build_standalone_xml_string

from .cda_identity import StableKey, stable_key
from .constants import NAMESPACES
from .diff_engine import collect_additions_updates_deletes
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

type StableKeyMap = dict[StableKey, WatchedNode]


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


def build_stable_keys(
    elem: etree._ElementTree, rules: list[RuleConfig]
) -> StableKeyMap:
    """Execute XPaths against element to stable key map."""
    key_map: StableKeyMap = {}

    for rule in rules:
        with measure_time(f"Execute {len(rule.xpaths)} xpaths for {rule.name}"):
            for xpath in rule.xpaths:
                vals = eval_xpath(elem, xpath)

                for val in vals:
                    key = stable_key(val)
                    print(val)
                    print(key)
                    print("\n\n")
                    if val.tag == "effectiveTime":
                        print("found effectiev time")
                        print(key)
                    if key is not None:
                        key_map[key] = WatchedNode(
                            node=val, tag=str(val.tag), xpath=xpath, rule_name=rule.name
                        )
    return key_map


def matching_nodes(
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


def matching_ancestry(node: etree._Element, cache: NodeCache) -> list[WatchedNode]:
    """Collect node and all ancestor matches."""
    return matching_nodes(node, node.iterancestors(), cache)


def matching_subtree(node: etree._Element, cache: NodeCache) -> list[WatchedNode]:
    """Collect node and all descendant matches."""
    return matching_nodes(node, node.iterdescendants(), cache)


# only diff for ignore list
def diff_xml(opts: DiffingOptions, config: Configuration) -> str:
    """Returns a XML diff string."""
    diff_output = DiffOutput()
    parser = etree.XMLParser(remove_blank_text=True, huge_tree=True)

    # uncomment for testing a ton of xpath evaluations
    # config.rules[0].xpaths *= 2000

    with measure_time("Parse XML files"):
        left_tree = etree.parse(opts.file1, parser)
        right_tree = etree.parse(opts.file2, parser)

    if config.mode == DiffMode.WATCH_LIST:
        with measure_time("Execute XPaths"):
            left_keys = build_stable_keys(left_tree, config.rules)
            right_keys = build_stable_keys(right_tree, config.rules)

        with measure_time("Find additions & deletions"):
            for key, el in left_keys.items():
                if key not in right_keys:
                    diff_output.changes.append(
                        Change(
                            xpath=el.xpath,
                            rule_name=el.rule_name,
                            changeType=ChangeType.DELETED,
                            xml=build_standalone_xml_string(el.node),
                        )
                    )
            for key, el in right_keys.items():
                if key not in left_keys:
                    diff_output.changes.append(
                        Change(
                            xpath=el.xpath,
                            rule_name=el.rule_name,
                            changeType=ChangeType.ADDED,
                            xml=build_standalone_xml_string(el.node),
                        )
                    )

        with measure_time("Find updates"):
            for key in left_keys.keys() & right_keys.keys():
                _added, updated, _deleted = collect_additions_updates_deletes(
                    left_keys[key].node, right_keys[key].node
                )

                el = right_keys[key]

                for [_before, after] in updated:
                    diff_output.changes.append(
                        Change(
                            xpath=el.xpath,
                            rule_name=el.rule_name,
                            changeType=ChangeType.UPDATED,
                            xml=build_standalone_xml_string(after),
                        )
                    )

    elif config.mode == DiffMode.IGNORE_LIST:
        with measure_time("Execute XPaths"):
            left_cache = build_cache(left_tree, config.rules)
            right_cache = build_cache(right_tree, config.rules)

        with measure_time("Perform diff and collect changes"):
            added, updated, deleted = collect_additions_updates_deletes(
                left_tree.getroot(), right_tree.getroot()
            )

        with measure_time("Process additions"):
            for after in added:
                if matching_ancestry(after, right_cache):
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
                if matching_ancestry(before, left_cache) or matching_ancestry(
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
                if matching_ancestry(before, left_cache):
                    continue

                diff_output.changes.append(
                    Change(
                        xpath=before.getroottree().getpath(before),
                        changeType=ChangeType.DELETED,
                        xml=build_standalone_xml_string(before),
                    )
                )

    return diff_output.model_dump_json(indent=2)


# always diff whole tree
def xdiff_xml(opts: DiffingOptions, config: Configuration) -> str:
    """Returns a XML diff string."""
    diff_output = DiffOutput()
    parser = etree.XMLParser(remove_blank_text=True, huge_tree=True)

    # uncomment for testing a ton of xpath evaluations
    # config.rules[0].xpaths *= 2000

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
                for match in matching_subtree(after, right_cache):
                    diff_output.changes.append(
                        Change(
                            xpath=match.xpath,
                            rule_name=match.rule_name,
                            changeType=ChangeType.ADDED,
                            xml=build_standalone_xml_string(match.effective_node),
                        )
                    )
            elif config.mode == DiffMode.IGNORE_LIST:
                if matching_ancestry(after, right_cache):
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
                for match in matching_ancestry(after, right_cache):
                    diff_output.changes.append(
                        Change(
                            xpath=match.xpath,
                            rule_name=match.rule_name,
                            changeType=ChangeType.UPDATED,
                            xml=build_standalone_xml_string(match.effective_node),
                        )
                    )
            elif config.mode == DiffMode.IGNORE_LIST:
                if matching_ancestry(before, left_cache) or matching_ancestry(
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
                for match in matching_subtree(before, left_cache):
                    diff_output.changes.append(
                        Change(
                            xpath=match.xpath,
                            rule_name=match.rule_name,
                            changeType=ChangeType.DELETED,
                            xml=build_standalone_xml_string(match.effective_node),
                        )
                    )
            elif config.mode == DiffMode.IGNORE_LIST:
                if matching_ancestry(before, left_cache):
                    continue

                diff_output.changes.append(
                    Change(
                        xpath=before.getroottree().getpath(before),
                        changeType=ChangeType.DELETED,
                        xml=build_standalone_xml_string(before),
                    )
                )

    return diff_output.model_dump_json(indent=2)
