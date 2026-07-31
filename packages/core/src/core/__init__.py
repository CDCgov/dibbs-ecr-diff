"""Core Difference in Docs functionality."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from lxml import etree
from lxml.etree import ElementTree

from .constants import (
    DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME,
    DEFAULT_ACTIONABLE_RULE_ID,
    NAMESPACES,
)
from .diff_collector import collect_additions_updates_deletes
from .models import (
    Change,
    ChangeType,
    Configuration,
    DiffMode,
    DiffOutput,
    Document,
    RuleConfig,
)
from .paths import xpath_with_predicates
from .performance import measure_time


@dataclass()
class WatchedNode:
    """Metadata for watched/ignored node cache."""

    node: etree._Element
    tag: str
    xpath: str
    rule_name: str
    rule_id: UUID
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
                        node=val,
                        tag=str(val.tag),
                        xpath=xpath,
                        rule_name=rule.name,
                        rule_id=rule.id,
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


def _get_document_metadata(root: etree._Element) -> Document:
    return Document(
        documentId=root.xpath("string(hl7:id/@root)", namespaces=NAMESPACES),
        versionNumber=root.xpath(
            "string(hl7:versionNumber/@value)", namespaces=NAMESPACES
        ),
    )


def _process_additions(
    added: list,
    mode: DiffMode,
    right_cache: NodeCache,
    current_document: Document,
) -> list[Change]:
    """Build ADDED change list for nodes present in the new document only.

    In WATCH_LIST mode, emits one change per rule match found within each
    added node's subtree. In IGNORE_LIST mode, emits one change per added
    node, skipping any node under an ignored ancestor. Added nodes live in
    the new tree, so xpathDocumentId is taken from ``current_document``.
    """
    changes: list[Change] = []
    for after in added:
        if mode == DiffMode.WATCH_LIST:
            for match in cached_subtree(after, right_cache):
                changes.append(
                    Change(
                        changeType=ChangeType.ADDED,
                        xpath=xpath_with_predicates(after),
                        xpathDocumentId=current_document.documentId,
                        isActionable=True,
                        actionabilityRuleId=match.rule_id,
                        actionabilityRuleDisplayName=match.rule_name,
                        anchor_node=after,
                    )
                )
        elif mode == DiffMode.IGNORE_LIST:
            if cached_ancestry(after, right_cache):
                continue
            changes.append(
                Change(
                    changeType=ChangeType.ADDED,
                    xpath=xpath_with_predicates(after),
                    xpathDocumentId=current_document.documentId,
                    isActionable=True,
                    actionabilityRuleId=DEFAULT_ACTIONABLE_RULE_ID,
                    actionabilityRuleDisplayName=(DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME),
                    anchor_node=after,
                )
            )
    return changes


def _process_updates(
    updated: list,
    mode: DiffMode,
    left_cache: NodeCache,
    right_cache: NodeCache,
    current_document: Document,
) -> list[Change]:
    """Build UPDATED change list for nodes that differ between the two documents.

    Each item in ``updated`` is a (before, after) pair. In WATCH_LIST mode,
    emits one change per rule match in the updated node's ancestry. In
    IGNORE_LIST mode, emits one change per updated node, skipping nodes that
    are ignored in either the old or new tree. xpathDocumentId is taken from
    ``current_document``.
    """
    changes: list[Change] = []
    for before, after in updated:
        if mode == DiffMode.WATCH_LIST:
            for match in cached_ancestry(after, right_cache):
                changes.append(
                    Change(
                        changeType=ChangeType.UPDATED,
                        xpath=xpath_with_predicates(after),
                        xpathDocumentId=current_document.documentId,
                        isActionable=True,
                        actionabilityRuleId=match.rule_id,
                        actionabilityRuleDisplayName=match.rule_name,
                        anchor_node=after,
                    )
                )
        elif mode == DiffMode.IGNORE_LIST:
            if cached_ancestry(before, left_cache) or cached_ancestry(
                after, right_cache
            ):
                continue
            changes.append(
                Change(
                    changeType=ChangeType.UPDATED,
                    xpath=xpath_with_predicates(after),
                    xpathDocumentId=current_document.documentId,
                    isActionable=True,
                    actionabilityRuleId=DEFAULT_ACTIONABLE_RULE_ID,
                    actionabilityRuleDisplayName=(DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME),
                    anchor_node=after,
                )
            )
    return changes


def _process_deletions(
    deleted: list,
    mode: DiffMode,
    left_cache: NodeCache,
    previous_document: Document,
) -> list[Change]:
    """Build DELETED change list for nodes present in the old document only.

    In WATCH_LIST mode, emits one change per rule match found within each
    deleted node's subtree. In IGNORE_LIST mode, emits one change per deleted
    node, skipping any node under an ignored ancestor. Deleted nodes live in
    the old tree, so xpathDocumentId is taken from ``previous_document``.
    """
    changes: list[Change] = []
    for before in deleted:
        if mode == DiffMode.WATCH_LIST:
            for match in cached_subtree(before, left_cache):
                changes.append(
                    Change(
                        changeType=ChangeType.DELETED,
                        xpath=xpath_with_predicates(before),
                        xpathDocumentId=previous_document.documentId,
                        isActionable=True,
                        actionabilityRuleId=match.rule_id,
                        actionabilityRuleDisplayName=match.rule_name,
                        anchor_node=before,
                    )
                )
        elif mode == DiffMode.IGNORE_LIST:
            if cached_ancestry(before, left_cache):
                continue
            changes.append(
                Change(
                    changeType=ChangeType.DELETED,
                    xpath=xpath_with_predicates(before),
                    xpathDocumentId=previous_document.documentId,
                    isActionable=True,
                    actionabilityRuleId=DEFAULT_ACTIONABLE_RULE_ID,
                    actionabilityRuleDisplayName=(DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME),
                    anchor_node=before,
                )
            )
    return changes


def diff_xml(
    before_tree: ElementTree, after_tree: ElementTree, config: Configuration
) -> DiffOutput:
    """Diff two XML documents and collect the changes into a DiffOutput.

    Compares the two trees and records every added, updated, and deleted node. The
    configuration mode decides which changes are reported: WATCH_LIST
    includes only nodes matching the configured rules, while IGNORE_LIST
    includes everything except nodes under an ignored ancestor.
    """
    previous_document = _get_document_metadata(before_tree.getroot())
    current_document = _get_document_metadata(after_tree.getroot())

    set_id = after_tree.xpath(
        "string(/hl7:ClinicalDocument/hl7:setId/@root)",
        namespaces=NAMESPACES,
    )

    diff_output = DiffOutput(
        generatedAt=datetime.now(UTC),
        setId=set_id,
        currentDocument=current_document,
        previousDocument=previous_document,
        hasActionableChanges=False,
    )

    with measure_time("Execute XPaths"):
        left_cache = build_cache(before_tree, config.rules)
        right_cache = build_cache(after_tree, config.rules)

    with measure_time("Perform diff and collect changes"):
        added, updated, deleted = collect_additions_updates_deletes(
            before_tree.getroot(), after_tree.getroot()
        )

    with measure_time("Process additions"):
        diff_output.changes.extend(
            _process_additions(added, config.mode, right_cache, current_document)
        )

    with measure_time("Process updates"):
        diff_output.changes.extend(
            _process_updates(
                updated, config.mode, left_cache, right_cache, current_document
            )
        )

    with measure_time("Process deletions"):
        diff_output.changes.extend(
            _process_deletions(deleted, config.mode, left_cache, previous_document)
        )

    diff_output.hasActionableChanges = any(
        change.isActionable for change in diff_output.changes
    )

    return diff_output
