"""Core Difference in Docs functionality."""

import re
from collections.abc import Iterable
from uuid import UUID

from lxml import etree
from lxml.etree import ElementTree

from .cda.tags import CODE_TAG, SECTION_TAG
from .constants import (
    DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME,
    DEFAULT_ACTIONABLE_RULE_ID,
    NAMESPACES,
)
from .datetime_utils import get_current_datetime
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


def _section_loinc_code_for_change(
    changed_element: etree._Element,
) -> str | None:
    """Return the nearest enclosing CDA section's well-formed LOINC code."""
    if changed_element.tag == SECTION_TAG:
        section = changed_element
    else:
        section = next(changed_element.iterancestors(tag=SECTION_TAG), None)

    if section is None:
        return None

    section_code = next(section.iterchildren(tag=CODE_TAG), None)
    if section_code is None:
        return None

    code = section_code.get("code")
    if (
        section_code.get("codeSystem") == _LOINC_CODE_SYSTEM_OID
        and code is not None
        and _LOINC_CODE_PATTERN.fullmatch(code)
    ):
        return code

    return None


def unique_rule_matches_for_change_type(
    rule_matches: Iterable[Rule],
    change_type: ChangeType,
) -> list[Rule]:
    """Return each applicable rule once, identified by its UUID.

    For example, ``//hl7:entry/descendant-or-self::*`` associates one rule
    with an ``<entry>`` and all of its descendant elements. Evaluating an entire
    added or deleted ``<entry>`` therefore finds that rule once for the
    ``<entry>`` itself and once for each descendant element. The same
    duplication can occur when multiple rule XPaths match related nodes or
    when ignore-mode update matching searches both documents' ancestries.

    All occurrences with the same UUID represent the same configured rule,
    and the matched node is not used to build the output Change. Keeping the
    first applicable occurrence therefore emits the change only once per rule.
    """
    first_match_by_rule: dict[UUID, Rule] = {}

    for rule_match in rule_matches:
        if change_type not in rule_match.changeTypes:
            continue

        if rule_match.id not in first_match_by_rule:
            first_match_by_rule[rule_match.id] = rule_match

    return list(first_match_by_rule.values())


def build_changes_for_rule_matches(
    element: etree._Element,
    change_type: ChangeType,
    document_id: str,
    rule_matches: Iterable[Rule],
    mode: DiffMode,
) -> list[Change]:
    """Build changes for applicable rule matches using the configured mode."""
    xpath = structural_xpath(element)
    section_loinc_code = _section_loinc_code_for_change(element)
    applicable_rules = unique_rule_matches_for_change_type(
        rule_matches,
        change_type,
    )
    if change_type in [ChangeType.ADDED, ChangeType.UPDATED]:
        augmentation_anchor_node = element
    else:
        augmentation_anchor_node = None

    if mode == DiffMode.WATCH_LIST:
        if applicable_rules:
            return [
                Change(
                    changeType=change_type,
                    xpath=xpath,
                    xpathDocumentId=document_id,
                    isActionable=True,
                    actionabilityRuleId=rule.id,
                    actionabilityRuleDisplayName=rule.displayName,
                    section_loinc_code=section_loinc_code,
                    augmentation_anchor_node=augmentation_anchor_node,
                )
                for rule in applicable_rules
            ]
        else:
            return [
                Change(
                    changeType=change_type,
                    xpath=xpath,
                    xpathDocumentId=document_id,
                    isActionable=False,
                    actionabilityRuleId=None,
                    actionabilityRuleDisplayName=None,
                    section_loinc_code=section_loinc_code,
                    augmentation_anchor_node=augmentation_anchor_node,
                )
            ]

    if mode == DiffMode.IGNORE_LIST:
        if applicable_rules:
            return [
                Change(
                    changeType=change_type,
                    xpath=xpath,
                    xpathDocumentId=document_id,
                    isActionable=False,
                    actionabilityRuleId=rule.id,
                    actionabilityRuleDisplayName=rule.displayName,
                    section_loinc_code=section_loinc_code,
                    augmentation_anchor_node=augmentation_anchor_node,
                )
                for rule in applicable_rules
            ]
        else:
            return [
                Change(
                    changeType=change_type,
                    xpath=xpath,
                    xpathDocumentId=document_id,
                    isActionable=True,
                    actionabilityRuleId=DEFAULT_ACTIONABLE_RULE_ID,
                    actionabilityRuleDisplayName=DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME,
                    section_loinc_code=section_loinc_code,
                    augmentation_anchor_node=augmentation_anchor_node,
                )
            ]

    return []


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
    rule_matches: list[Rule] = []
    changes: list[Change] = []
    for added_element in added:
        if mode == DiffMode.WATCH_LIST:
            rule_matches = rule_matches_for_node_and_descendants(
                added_element,
                right_rule_match_cache,
            )
        elif mode == DiffMode.IGNORE_LIST:
            rule_matches = rule_matches_for_node_and_ancestors(
                added_element,
                right_rule_match_cache,
            )

        changes.extend(
            build_changes_for_rule_matches(
                element=added_element,
                change_type=ChangeType.ADDED,
                document_id=current_document.documentId,
                rule_matches=rule_matches,
                mode=mode,
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
    rule_matches: list[Rule] = []
    for before, after in updated:
        if mode == DiffMode.WATCH_LIST:
            rule_matches = right_rule_match_cache.get(after, [])
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
        changes.extend(
            build_changes_for_rule_matches(
                element=after,
                change_type=ChangeType.UPDATED,
                document_id=current_document.documentId,
                rule_matches=rule_matches,
                mode=mode,
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
    rule_matches: list[Rule] = []
    for deleted_element in deleted:
        if mode == DiffMode.WATCH_LIST:
            rule_matches = rule_matches_for_node_and_descendants(
                deleted_element,
                left_rule_match_cache,
            )
        elif mode == DiffMode.IGNORE_LIST:
            rule_matches = rule_matches_for_node_and_ancestors(
                deleted_element,
                left_rule_match_cache,
            )

        changes.extend(
            build_changes_for_rule_matches(
                element=deleted_element,
                change_type=ChangeType.DELETED,
                document_id=previous_document.documentId,
                rule_matches=rule_matches,
                mode=mode,
            )
        )
    return changes


def diff_xml(
    before_tree: ElementTree, after_tree: ElementTree, config: Configuration
) -> DiffOutput:
    """Diff two XML documents and collect the changes into a DiffOutput.

    Compares the two trees and detects every added, updated, and deleted node. The
    configuration determines whether each detected change is actionable or
    non-actionable.
    """
    previous_document = _get_document_metadata(before_tree.getroot())
    current_document = _get_document_metadata(after_tree.getroot())

    set_id = after_tree.xpath(
        "string(/hl7:ClinicalDocument/hl7:setId/@root)",
        namespaces=NAMESPACES,
    )

    with measure_time("Execute XPaths"):
        left_rule_match_cache = build_rule_match_cache(before_tree, config.rules)
        right_rule_match_cache = build_rule_match_cache(after_tree, config.rules)

    with measure_time("Perform diff and collect changes"):
        added, updated, deleted = collect_additions_updates_deletes(
            before_tree.getroot(), after_tree.getroot()
        )

    processed_changes: list[Change] = []

    with measure_time("Process additions"):
        processed_changes.extend(
            _process_additions(
                added,
                config.mode,
                right_rule_match_cache,
                current_document,
            )
        )

    with measure_time("Process updates"):
        processed_changes.extend(
            _process_updates(
                updated,
                config.mode,
                left_rule_match_cache,
                right_rule_match_cache,
                current_document,
            )
        )

    with measure_time("Process deletions"):
        processed_changes.extend(
            _process_deletions(
                deleted, config.mode, left_rule_match_cache, previous_document
            )
        )

    return DiffOutput(
        generatedAt=get_current_datetime(),
        configurationId=config.id,
        configurationVersion=config.configVersion,
        configurationDisplayName=config.displayName,
        setId=set_id,
        currentDocument=current_document,
        previousDocument=previous_document,
        hasDetectedChanges=bool(added or updated or deleted),
        hasActionableChanges=any(change.isActionable for change in processed_changes),
        changes=processed_changes,
    )
