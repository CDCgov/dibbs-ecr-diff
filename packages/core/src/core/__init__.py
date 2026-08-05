"""Core Difference in Docs functionality."""

from collections.abc import Iterable
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
    Rule,
)
from .paths import structural_xpath
from .performance import measure_time

# Maps XML nodes matched by configured XPaths to all their rules.
type RuleMatchCache = dict[etree._Element, list[Rule]]


def eval_xpath(
    elem: etree._Element | etree._ElementTree, xpath_expr: str
) -> list[etree._Element]:
    """Evaluate an XPath and return resulting list of elements."""
    return elem.xpath(xpath_expr, namespaces=NAMESPACES) or []


def build_rule_match_cache(
    elem: etree._ElementTree, rules: list[Rule]
) -> RuleMatchCache:
    """Evaluate rule XPaths and map each matched XML node to all its rules."""
    rule_match_cache: RuleMatchCache = {}

    for rule in rules:
        with measure_time(f"Execute {len(rule.xpaths)} xpaths for {rule.displayName}"):
            for xpath in rule.xpaths:
                matched_nodes = eval_xpath(elem, xpath)

                for matched_node in matched_nodes:
                    matched_rules = rule_match_cache.setdefault(matched_node, [])
                    # Avoid caching the same rule more than once when multiple
                    # XPath expressions from that rule match the same node.
                    if not any(
                        matched_rule.id == rule.id for matched_rule in matched_rules
                    ):
                        matched_rules.append(rule)
    return rule_match_cache


def rule_matches_for_node_and_related_nodes(
    node: etree._Element,
    related_nodes: Iterable[etree._Element],
    rule_match_cache: RuleMatchCache,
) -> list[Rule]:
    """Return rules matching the node or any supplied related node."""
    rule_matches: list[Rule] = []

    for related_node in [node, *related_nodes]:
        rule_matches.extend(rule_match_cache.get(related_node, []))

    return rule_matches


def rule_matches_for_node_and_ancestors(
    node: etree._Element,
    rule_match_cache: RuleMatchCache,
) -> list[Rule]:
    """Collect node and all ancestor matches."""
    return rule_matches_for_node_and_related_nodes(
        node, node.iterancestors(), rule_match_cache
    )


def rule_matches_for_node_and_descendants(
    node: etree._Element,
    rule_match_cache: RuleMatchCache,
) -> list[Rule]:
    """Collect node and all descendant matches."""
    return rule_matches_for_node_and_related_nodes(
        node, node.iterdescendants(), rule_match_cache
    )


def _get_document_metadata(root: etree._Element) -> Document:
    return Document(
        documentId=root.xpath("string(hl7:id/@root)", namespaces=NAMESPACES),
        versionNumber=root.xpath(
            "string(hl7:versionNumber/@value)", namespaces=NAMESPACES
        ),
    )


def unique_rule_matches_for_change_type(
    rule_matches: Iterable[Rule],
    change_type: ChangeType,
) -> list[Rule]:
    """Return one match per rule for the current XML change.

    Ignore rules that do not apply to the change type. A change can match an
    applicable rule through several related XML elements, so keep its first
    match.
    """
    first_match_by_rule: dict[UUID, Rule] = {}

    for rule_match in rule_matches:
        if change_type not in rule_match.changeTypes:
            continue

        if rule_match.id not in first_match_by_rule:
            first_match_by_rule[rule_match.id] = rule_match

    return list(first_match_by_rule.values())


def has_ignore_rule_for_change_type(
    rule_matches: Iterable[Rule],
    change_type: ChangeType,
) -> bool:
    """Return true if any of the ignore-rule matches has the change type."""
    for rule_match in rule_matches:
        if change_type in rule_match.changeTypes:
            return True

    return False


def _process_additions(
    added: list,
    mode: DiffMode,
    right_rule_match_cache: RuleMatchCache,
    current_document: Document,
) -> list[Change]:
    """Build ADDED change list for nodes present in the new document only.

    WATCH_LIST additions are actionable when an applicable rule matches the
    added subtree. IGNORE_LIST additions are nonactionable when an applicable
    rule matches the node or an ancestor. All other additions are retained
    with the mode's default actionability.
    """
    changes: list[Change] = []
    for added_element in added:
        if mode == DiffMode.WATCH_LIST:
            applicable_rules = unique_rule_matches_for_change_type(
                rule_matches_for_node_and_descendants(
                    added_element,
                    right_rule_match_cache,
                ),
                ChangeType.ADDED,
            )
            for rule_match in applicable_rules:
                changes.append(
                    Change(
                        changeType=ChangeType.ADDED,
                        xpath=structural_xpath(added_element),
                        xpathDocumentId=current_document.documentId,
                        isActionable=True,
                        actionabilityRuleId=rule_match.id,
                        actionabilityRuleDisplayName=rule_match.displayName,
                    )
                )

            if not applicable_rules:
                changes.append(
                    Change(
                        changeType=ChangeType.ADDED,
                        xpath=structural_xpath(added_element),
                        xpathDocumentId=current_document.documentId,
                        isActionable=False,
                        actionabilityRuleId=None,
                        actionabilityRuleDisplayName=None,
                    )
                )
        elif mode == DiffMode.IGNORE_LIST:
            ignore_rules = unique_rule_matches_for_change_type(
                rule_matches_for_node_and_ancestors(
                    added_element,
                    right_rule_match_cache,
                ),
                ChangeType.ADDED,
            )
            if ignore_rules:
                for ignore_rule in ignore_rules:
                    changes.append(
                        Change(
                            changeType=ChangeType.ADDED,
                            xpath=structural_xpath(added_element),
                            xpathDocumentId=current_document.documentId,
                            isActionable=False,
                            actionabilityRuleId=ignore_rule.id,
                            actionabilityRuleDisplayName=ignore_rule.displayName,
                        )
                    )
                continue

            changes.append(
                Change(
                    changeType=ChangeType.ADDED,
                    xpath=structural_xpath(added_element),
                    xpathDocumentId=current_document.documentId,
                    isActionable=True,
                    actionabilityRuleId=DEFAULT_ACTIONABLE_RULE_ID,
                    actionabilityRuleDisplayName=DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME,
                )
            )
    return changes


def _process_updates(
    updated: list,
    mode: DiffMode,
    left_rule_match_cache: RuleMatchCache,
    right_rule_match_cache: RuleMatchCache,
    current_document: Document,
) -> list[Change]:
    """Build UPDATED change list for nodes that differ between the two documents.

    WATCH_LIST updates are actionable when the after node directly matches an
    applicable rule. IGNORE_LIST updates are nonactionable when an applicable
    rule matches the node or an ancestor in either document. All other updates
    are retained with the mode's default actionability.
    """
    changes: list[Change] = []
    for before, after in updated:
        if mode == DiffMode.WATCH_LIST:
            applicable_rules = unique_rule_matches_for_change_type(
                right_rule_match_cache.get(after, []),
                ChangeType.UPDATED,
            )
            for rule_match in applicable_rules:
                changes.append(
                    Change(
                        changeType=ChangeType.UPDATED,
                        xpath=structural_xpath(after),
                        xpathDocumentId=current_document.documentId,
                        isActionable=True,
                        actionabilityRuleId=rule_match.id,
                        actionabilityRuleDisplayName=rule_match.displayName,
                    )
                )

            if not applicable_rules:
                changes.append(
                    Change(
                        changeType=ChangeType.UPDATED,
                        xpath=structural_xpath(after),
                        xpathDocumentId=current_document.documentId,
                        isActionable=False,
                        actionabilityRuleId=None,
                        actionabilityRuleDisplayName=None,
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
            ignore_rules = unique_rule_matches_for_change_type(
                rule_matches,
                ChangeType.UPDATED,
            )
            if ignore_rules:
                for ignore_rule in ignore_rules:
                    changes.append(
                        Change(
                            changeType=ChangeType.UPDATED,
                            xpath=structural_xpath(after),
                            xpathDocumentId=current_document.documentId,
                            isActionable=False,
                            actionabilityRuleId=ignore_rule.id,
                            actionabilityRuleDisplayName=ignore_rule.displayName,
                        )
                    )
                continue
            changes.append(
                Change(
                    changeType=ChangeType.UPDATED,
                    xpath=structural_xpath(after),
                    xpathDocumentId=current_document.documentId,
                    isActionable=True,
                    actionabilityRuleId=DEFAULT_ACTIONABLE_RULE_ID,
                    actionabilityRuleDisplayName=DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME,
                )
            )
    return changes


def _process_deletions(
    deleted: list,
    mode: DiffMode,
    left_rule_match_cache: RuleMatchCache,
    previous_document: Document,
) -> list[Change]:
    """Build DELETED change list for nodes present in the old document only.

    WATCH_LIST deletions are actionable when an applicable rule matches the
    deleted subtree. IGNORE_LIST deletions are nonactionable when an applicable
    rule matches the node or an ancestor. All other deletions are retained with
    the mode's default actionability.
    """
    changes: list[Change] = []
    for deleted_element in deleted:
        if mode == DiffMode.WATCH_LIST:
            applicable_rules = unique_rule_matches_for_change_type(
                rule_matches_for_node_and_descendants(
                    deleted_element,
                    left_rule_match_cache,
                ),
                ChangeType.DELETED,
            )
            for rule_match in applicable_rules:
                changes.append(
                    Change(
                        changeType=ChangeType.DELETED,
                        xpath=structural_xpath(deleted_element),
                        xpathDocumentId=previous_document.documentId,
                        isActionable=True,
                        actionabilityRuleId=rule_match.id,
                        actionabilityRuleDisplayName=rule_match.displayName,
                    )
                )

            if not applicable_rules:
                changes.append(
                    Change(
                        changeType=ChangeType.DELETED,
                        xpath=structural_xpath(deleted_element),
                        xpathDocumentId=previous_document.documentId,
                        isActionable=False,
                        actionabilityRuleId=None,
                        actionabilityRuleDisplayName=None,
                    )
                )
        elif mode == DiffMode.IGNORE_LIST:
            ignore_rules = unique_rule_matches_for_change_type(
                rule_matches_for_node_and_ancestors(
                    deleted_element,
                    left_rule_match_cache,
                ),
                ChangeType.DELETED,
            )
            if ignore_rules:
                for ignore_rule in ignore_rules:
                    changes.append(
                        Change(
                            changeType=ChangeType.DELETED,
                            xpath=structural_xpath(deleted_element),
                            xpathDocumentId=previous_document.documentId,
                            isActionable=False,
                            actionabilityRuleId=ignore_rule.id,
                            actionabilityRuleDisplayName=ignore_rule.displayName,
                        )
                    )
                continue
            changes.append(
                Change(
                    changeType=ChangeType.DELETED,
                    xpath=structural_xpath(deleted_element),
                    xpathDocumentId=previous_document.documentId,
                    isActionable=True,
                    actionabilityRuleId=DEFAULT_ACTIONABLE_RULE_ID,
                    actionabilityRuleDisplayName=DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME,
                )
            )
    return changes


def diff_xml(opts: DiffingOptions, config: Configuration) -> DiffOutput:
    """Diff two XML documents and collect the changes into a DiffOutput.

    Compares the two files named in ``opts`` (file1 = previous, file2 =
    current) and records every detected added, updated, and deleted node. The
    configuration mode determines whether each reported change is actionable.
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
        configurationId=config.id,
        configurationVersion=config.configVersion,
        configurationDisplayName=config.displayName,
        setId=set_id,
        currentDocument=current_document,
        previousDocument=previous_document,
    )

    with measure_time("Execute XPaths"):
        left_rule_match_cache = build_rule_match_cache(left_tree, config.rules)
        right_rule_match_cache = build_rule_match_cache(right_tree, config.rules)

    with measure_time("Perform diff and collect changes"):
        added, updated, deleted = collect_additions_updates_deletes(
            left_tree.getroot(), right_tree.getroot()
        )

    diff_output.hasDetectedChanges = bool(added or updated or deleted)

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
