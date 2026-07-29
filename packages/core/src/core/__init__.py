"""Core Difference in Docs functionality."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from lxml import etree

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
    DiffingOptions,
    DiffMode,
    DiffOutput,
    Document,
    RuleConfig,
)
from .paths import xpath_with_predicates
from .performance import measure_time


@dataclass()
class RuleMatchNode:
    """Metadata for watched/ignored node cache."""

    node: etree._Element
    tag: str
    xpath: str
    rule_name: str
    rule_id: UUID
    change_types: frozenset[ChangeType]


"""Used to cache nodes from evaluated rule XPaths."""
type RuleMatchCache = dict[etree._Element, RuleMatchNode]


def eval_xpath(
    elem: etree._Element | etree._ElementTree, xpath_expr: str
) -> list[etree._Element]:
    """Evaluate an XPath and return resulting list of elements."""
    return elem.xpath(xpath_expr, namespaces=NAMESPACES) or []


def build_cache(elem: etree._ElementTree, rules: list[RuleConfig]) -> RuleMatchCache:
    """Execute XPaths against element to build node cache."""
    nodes: RuleMatchCache = {}

    for rule in rules:
        with measure_time(f"Execute {len(rule.xpaths)} xpaths for {rule.displayName}"):
            for xpath in rule.xpaths:
                vals = eval_xpath(elem, xpath)

                for val in vals:
                    nodes[val] = RuleMatchNode(
                        node=val,
                        tag=str(val.tag),
                        xpath=xpath,
                        rule_name=rule.displayName,
                        rule_id=rule.id,
                        change_types=frozenset(rule.changeTypes),
                    )
    return nodes


def nodes_in_cache(
    node: etree._Element,
    related_nodes: Iterable[etree._Element],
    cache: RuleMatchCache,
) -> list[RuleMatchNode]:
    """Generic method for collecting all matched nodes from a cache."""
    matches: list[RuleMatchNode] = []

    for related_node in [node, *related_nodes]:
        cache_match = cache.get(related_node)
        if cache_match is not None:
            matches.append(cache_match)

    return matches


def rule_matches_for_node_and_ancestors(
    node: etree._Element,
    cache: RuleMatchCache,
) -> list[RuleMatchNode]:
    """Collect node and all ancestor matches."""
    return nodes_in_cache(node, node.iterancestors(), cache)


def rule_matches_for_node_and_descendants(
    node: etree._Element,
    cache: RuleMatchCache,
) -> list[RuleMatchNode]:
    """Collect node and all descendant matches."""
    return nodes_in_cache(node, node.iterdescendants(), cache)


def _get_document_metadata(root: etree._Element) -> Document:
    return Document(
        documentId=root.xpath("string(hl7:id/@root)", namespaces=NAMESPACES),
        versionNumber=root.xpath(
            "string(hl7:versionNumber/@value)", namespaces=NAMESPACES
        ),
    )


def unique_rule_matches(
    matches: Iterable[RuleMatchNode],
    change_type: ChangeType,
) -> list[RuleMatchNode]:
    """Return one match per rule for the current XML change.

    Ignore rules that do not apply to the change type. A change can match an
    applicable rule through several related XML elements, so keep its first
    match.
    """
    first_match_by_rule: dict[UUID, RuleMatchNode] = {}

    for match in matches:
        if change_type not in match.change_types:
            continue

        if match.rule_id not in first_match_by_rule:
            first_match_by_rule[match.rule_id] = match

    return list(first_match_by_rule.values())


def change_is_ignorable(
    matches: Iterable[RuleMatchNode],
    ignorable_change_type: ChangeType,
) -> bool:
    """Return true if any match has the ignorable change type."""
    for match in matches:
        if ignorable_change_type in match.change_types:
            return True

    return False


def _process_additions(
    added: list,
    mode: DiffMode,
    right_rule_match_cache: RuleMatchCache,
    current_document: Document,
) -> list[Change]:
    """Build ADDED change list for nodes present in the new document only.

    In WATCH_LIST mode, emits one change per rule match found within each
    added node's subtree. In IGNORE_LIST mode, emits one change per added
    node, skipping any node under an ignored ancestor. Added nodes live in
    the new tree, so xpathDocumentId is taken from ``current_document``.
    """
    actionable_added_elements: list[Change] = []
    for added_element in added:
        if mode == DiffMode.WATCH_LIST:
            for actionable_added_element in unique_rule_matches(
                rule_matches_for_node_and_descendants(
                    added_element,
                    right_rule_match_cache,
                ),
                ChangeType.ADDED,
            ):
                actionable_added_elements.append(
                    Change(
                        changeType=ChangeType.ADDED,
                        xpath=xpath_with_predicates(added_element),
                        xpathDocumentId=current_document.documentId,
                        isActionable=True,
                        actionabilityRuleId=actionable_added_element.rule_id,
                        actionabilityRuleDisplayName=actionable_added_element.rule_name,
                    )
                )
        elif mode == DiffMode.IGNORE_LIST:
            if change_is_ignorable(
                rule_matches_for_node_and_ancestors(
                    added_element,
                    right_rule_match_cache,
                ),
                ChangeType.ADDED,
            ):
                continue

            actionable_added_elements.append(
                Change(
                    changeType=ChangeType.ADDED,
                    xpath=xpath_with_predicates(added_element),
                    xpathDocumentId=current_document.documentId,
                    isActionable=True,
                    actionabilityRuleId=DEFAULT_ACTIONABLE_RULE_ID,
                    actionabilityRuleDisplayName=(DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME),
                )
            )
    return actionable_added_elements


def _process_updates(
    updated: list,
    mode: DiffMode,
    left_rule_match_cache: RuleMatchCache,
    right_rule_match_cache: RuleMatchCache,
    current_document: Document,
) -> list[Change]:
    """Build UPDATED change list for nodes that differ between the two documents.

    Each item in ``updated`` is a (before, after) pair. In WATCH_LIST mode,
    emits a change when the after node directly matches an applicable rule. In
    IGNORE_LIST mode, emits one change per updated node unless that node or one
    of its ancestors matches an applicable rule in either the previous or
    current document. xpathDocumentId is taken from ``current_document``.
    """
    actionable_updated_elements: list[Change] = []
    for before, after in updated:
        if mode == DiffMode.WATCH_LIST:
            actionable_updated_element = right_rule_match_cache.get(after)
            if (
                actionable_updated_element is not None
                and ChangeType.UPDATED in actionable_updated_element.change_types
            ):
                actionable_updated_elements.append(
                    Change(
                        changeType=ChangeType.UPDATED,
                        xpath=xpath_with_predicates(after),
                        xpathDocumentId=current_document.documentId,
                        isActionable=True,
                        actionabilityRuleId=actionable_updated_element.rule_id,
                        actionabilityRuleDisplayName=actionable_updated_element.rule_name,
                    )
                )
        elif mode == DiffMode.IGNORE_LIST:
            rule_matches = [
                *rule_matches_for_node_and_ancestors(
                    before,
                    left_rule_match_cache,
                ),
                *rule_matches_for_node_and_ancestors(
                    after,
                    right_rule_match_cache,
                ),
            ]
            if change_is_ignorable(
                rule_matches,
                ChangeType.UPDATED,
            ):
                continue
            actionable_updated_elements.append(
                Change(
                    changeType=ChangeType.UPDATED,
                    xpath=xpath_with_predicates(after),
                    xpathDocumentId=current_document.documentId,
                    isActionable=True,
                    actionabilityRuleId=DEFAULT_ACTIONABLE_RULE_ID,
                    actionabilityRuleDisplayName=(DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME),
                )
            )
    return actionable_updated_elements


def _process_deletions(
    deleted: list,
    mode: DiffMode,
    left_rule_match_cache: RuleMatchCache,
    previous_document: Document,
) -> list[Change]:
    """Build DELETED change list for nodes present in the old document only.

    In WATCH_LIST mode, emits one change per rule match found within each
    deleted node's subtree. In IGNORE_LIST mode, emits one change per deleted
    node, skipping any node under an ignored ancestor. Deleted nodes live in
    the old tree, so xpathDocumentId is taken from ``previous_document``.
    """
    actionable_deleted_elements: list[Change] = []
    for deleted_element in deleted:
        if mode == DiffMode.WATCH_LIST:
            for actionable_deleted_element in unique_rule_matches(
                rule_matches_for_node_and_descendants(
                    deleted_element,
                    left_rule_match_cache,
                ),
                ChangeType.DELETED,
            ):
                actionable_deleted_elements.append(
                    Change(
                        changeType=ChangeType.DELETED,
                        xpath=xpath_with_predicates(deleted_element),
                        xpathDocumentId=previous_document.documentId,
                        isActionable=True,
                        actionabilityRuleId=actionable_deleted_element.rule_id,
                        actionabilityRuleDisplayName=actionable_deleted_element.rule_name,
                    )
                )
        elif mode == DiffMode.IGNORE_LIST:
            if change_is_ignorable(
                rule_matches_for_node_and_ancestors(
                    deleted_element,
                    left_rule_match_cache,
                ),
                ChangeType.DELETED,
            ):
                continue
            actionable_deleted_elements.append(
                Change(
                    changeType=ChangeType.DELETED,
                    xpath=xpath_with_predicates(deleted_element),
                    xpathDocumentId=previous_document.documentId,
                    isActionable=True,
                    actionabilityRuleId=DEFAULT_ACTIONABLE_RULE_ID,
                    actionabilityRuleDisplayName=(DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME),
                )
            )
    return actionable_deleted_elements


def diff_xml(opts: DiffingOptions, config: Configuration) -> DiffOutput:
    """Diff two XML documents and collect the changes into a DiffOutput.

    Compares the two files named in ``opts`` (file1 = previous, file2 =
    current) and records every added, updated, and deleted node. The
    configuration mode decides which changes are reported: WATCH_LIST
    includes only nodes matching the configured rules, while IGNORE_LIST
    includes everything except nodes under an ignored ancestor.
    """
    parser = etree.XMLParser(remove_blank_text=True, huge_tree=True)

    with measure_time("Parse XML files"):
        left_tree = etree.parse(opts.file1, parser)
        right_tree = etree.parse(opts.file2, parser)

    previous_document = _get_document_metadata(left_tree.getroot())
    current_document = _get_document_metadata(right_tree.getroot())

    set_id = right_tree.xpath(
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
        left_rule_match_cache = build_cache(left_tree, config.rules)
        right_rule_match_cache = build_cache(right_tree, config.rules)

    with measure_time("Perform diff and collect changes"):
        added, updated, deleted = collect_additions_updates_deletes(
            left_tree.getroot(), right_tree.getroot()
        )

    with measure_time("Process additions"):
        diff_output.changes.extend(
            _process_additions(
                added,
                config.mode,
                right_rule_match_cache,
                current_document,
            )
        )

    with measure_time("Process updates"):
        diff_output.changes.extend(
            _process_updates(
                updated,
                config.mode,
                left_rule_match_cache,
                right_rule_match_cache,
                current_document,
            )
        )

    with measure_time("Process deletions"):
        diff_output.changes.extend(
            _process_deletions(
                deleted, config.mode, left_rule_match_cache, previous_document
            )
        )

    diff_output.hasActionableChanges = any(
        change.isActionable for change in diff_output.changes
    )

    return diff_output
