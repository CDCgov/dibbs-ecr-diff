"""Core Difference in Docs functionality."""

import re
from collections.abc import Iterable
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
    Rule,
)
from .paths import structural_xpath
from .performance import measure_time
from .xml_utils import hl7_clark_tag

# Maps XML nodes matched by configured XPaths to all their rules.
type RuleMatchCache = dict[etree._Element, list[Rule]]

_LOINC_CODE_SYSTEM_OID = "2.16.840.1.113883.6.1"
_LOINC_CODE_PATTERN = re.compile(r"\d{1,8}-\d")


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


def _associated_code_elements(
    context: etree._Element,
) -> Iterable[etree._Element]:
    """Yield coded elements directly associated with an XML context."""
    yield context

    translation_tag = hl7_clark_tag("translation")
    yield from context.iterchildren(tag=translation_tag)

    for code_element in context.iterchildren(tag=hl7_clark_tag("code")):
        yield code_element
        yield from code_element.iterchildren(tag=translation_tag)


def _closest_associated_loinc_code(
    changed_element: etree._Element,
) -> str | None:
    """Return the nearest well-formed LOINC code associated with an element."""
    for context in (changed_element, *changed_element.iterancestors()):
        for coded_element in _associated_code_elements(context):
            code = coded_element.get("code")
            if (
                coded_element.get("codeSystem") == _LOINC_CODE_SYSTEM_OID
                and code is not None
                and _LOINC_CODE_PATTERN.fullmatch(code)
            ):
                return code

    return None


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

    In WATCH_LIST mode, emits one change per rule match found within each
    added node's subtree. In IGNORE_LIST mode, emits one change per added
    node unless the node or one of its ancestors matches an ignore rule.
    Added nodes live in the new tree, so xpathDocumentId is taken from
    ``current_document``.
    """
    actionable_changes: list[Change] = []
    for added_element in added:
        closest_associated_loinc_code = _closest_associated_loinc_code(added_element)
        if mode == DiffMode.WATCH_LIST:
            for rule_match in unique_rule_matches_for_change_type(
                rule_matches_for_node_and_descendants(
                    added_element,
                    right_rule_match_cache,
                ),
                ChangeType.ADDED,
            ):
                actionable_changes.append(
                    Change(
                        changeType=ChangeType.ADDED,
                        xpath=structural_xpath(added_element),
                        xpathDocumentId=current_document.documentId,
                        isActionable=True,
                        actionabilityRuleId=rule_match.id,
                        actionabilityRuleDisplayName=rule_match.displayName,
                        closest_associated_loinc_code=closest_associated_loinc_code,
                        augmentation_anchor_node=added_element,
                    )
                )
        elif mode == DiffMode.IGNORE_LIST:
            if has_ignore_rule_for_change_type(
                rule_matches_for_node_and_ancestors(
                    added_element,
                    right_rule_match_cache,
                ),
                ChangeType.ADDED,
            ):
                continue

            actionable_changes.append(
                Change(
                    changeType=ChangeType.ADDED,
                    xpath=structural_xpath(added_element),
                    xpathDocumentId=current_document.documentId,
                    isActionable=True,
                    actionabilityRuleId=DEFAULT_ACTIONABLE_RULE_ID,
                    actionabilityRuleDisplayName=DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME,
                    closest_associated_loinc_code=closest_associated_loinc_code,
                    augmentation_anchor_node=added_element,
                )
            )
    return actionable_changes


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
    actionable_changes: list[Change] = []
    for before, after in updated:
        closest_associated_loinc_code = _closest_associated_loinc_code(after)
        if mode == DiffMode.WATCH_LIST:
            for rule_match in unique_rule_matches_for_change_type(
                right_rule_match_cache.get(after, []),
                ChangeType.UPDATED,
            ):
                actionable_changes.append(
                    Change(
                        changeType=ChangeType.UPDATED,
                        xpath=structural_xpath(after),
                        xpathDocumentId=current_document.documentId,
                        isActionable=True,
                        actionabilityRuleId=rule_match.id,
                        actionabilityRuleDisplayName=rule_match.displayName,
                        closest_associated_loinc_code=closest_associated_loinc_code,
                        augmentation_anchor_node=after,
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
            if has_ignore_rule_for_change_type(
                rule_matches,
                ChangeType.UPDATED,
            ):
                continue
            actionable_changes.append(
                Change(
                    changeType=ChangeType.UPDATED,
                    xpath=structural_xpath(after),
                    xpathDocumentId=current_document.documentId,
                    isActionable=True,
                    actionabilityRuleId=DEFAULT_ACTIONABLE_RULE_ID,
                    actionabilityRuleDisplayName=DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME,
                    closest_associated_loinc_code=closest_associated_loinc_code,
                    augmentation_anchor_node=after,
                )
            )
    return actionable_changes


def _process_deletions(
    deleted: list,
    mode: DiffMode,
    left_rule_match_cache: RuleMatchCache,
    previous_document: Document,
) -> list[Change]:
    """Build DELETED change list for nodes present in the old document only.

    In WATCH_LIST mode, emits one change per rule match found within each
    deleted node's subtree. In IGNORE_LIST mode, emits one change per deleted
    node unless the node or one of its ancestors matches an ignore rule.
    Deleted nodes live in the old tree, so xpathDocumentId is taken from
    ``previous_document``.
    """
    actionable_changes: list[Change] = []
    for deleted_element in deleted:
        closest_associated_loinc_code = _closest_associated_loinc_code(deleted_element)
        if mode == DiffMode.WATCH_LIST:
            for rule_match in unique_rule_matches_for_change_type(
                rule_matches_for_node_and_descendants(
                    deleted_element,
                    left_rule_match_cache,
                ),
                ChangeType.DELETED,
            ):
                actionable_changes.append(
                    Change(
                        changeType=ChangeType.DELETED,
                        xpath=structural_xpath(deleted_element),
                        xpathDocumentId=previous_document.documentId,
                        isActionable=True,
                        actionabilityRuleId=rule_match.id,
                        actionabilityRuleDisplayName=rule_match.displayName,
                        closest_associated_loinc_code=closest_associated_loinc_code,
                    )
                )
        elif mode == DiffMode.IGNORE_LIST:
            if has_ignore_rule_for_change_type(
                rule_matches_for_node_and_ancestors(
                    deleted_element,
                    left_rule_match_cache,
                ),
                ChangeType.DELETED,
            ):
                continue
            actionable_changes.append(
                Change(
                    changeType=ChangeType.DELETED,
                    xpath=structural_xpath(deleted_element),
                    xpathDocumentId=previous_document.documentId,
                    isActionable=True,
                    actionabilityRuleId=DEFAULT_ACTIONABLE_RULE_ID,
                    actionabilityRuleDisplayName=DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME,
                    closest_associated_loinc_code=closest_associated_loinc_code,
                )
            )
    return actionable_changes


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
        configurationId=config.id,
        configurationVersion=config.configVersion,
        configurationDisplayName=config.displayName,
        setId=set_id,
        currentDocument=current_document,
        previousDocument=previous_document,
    )

    with measure_time("Execute XPaths"):
        left_rule_match_cache = build_rule_match_cache(before_tree, config.rules)
        right_rule_match_cache = build_rule_match_cache(after_tree, config.rules)

    with measure_time("Perform diff and collect changes"):
        added, updated, deleted = collect_additions_updates_deletes(
            before_tree.getroot(), after_tree.getroot()
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
