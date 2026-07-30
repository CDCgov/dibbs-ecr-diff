from uuid import UUID

import pytest
from core import (
    _get_document_metadata,
    _process_additions,
    _process_deletions,
    _process_updates,
    build_rule_match_cache,
    change_is_ignorable,
    rule_matches_for_node_and_ancestors,
    rule_matches_for_node_and_descendants,
    unique_rule_matches,
)
from core.constants import (
    DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME,
    DEFAULT_ACTIONABLE_RULE_ID,
)
from core.models import Change, ChangeType, DiffMode, Document, Rule
from core.paths import structural_xpath
from helpers import HL7_NS, elem, find_one
from pydantic import ValidationError

RULE_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
RULE_NAME = "Relevant clinical observation"


def rule(
    change_types: frozenset[ChangeType] = frozenset(
        {
            ChangeType.ADDED,
            ChangeType.UPDATED,
            ChangeType.DELETED,
        }
    ),
) -> Rule:
    return Rule(
        id=RULE_ID,
        displayName=RULE_NAME,
        changeTypes=change_types,
    )


def assert_change(
    change: Change,
    *,
    change_type: ChangeType,
    node,
    document_id: str,
    rule_id: UUID,
    rule_name: str,
) -> None:
    assert change.changeType == change_type
    assert change.xpath == structural_xpath(node)
    assert change.xpathDocumentId == document_id
    assert change.isActionable is True
    assert change.actionabilityRuleId == rule_id
    assert change.actionabilityRuleDisplayName == rule_name


def test_get_document_metadata_extracts_document_id_and_version_number():
    root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <id root="document-id"/>
          <versionNumber value="7"/>
          <component>
            <observation>
              <id root="nested-clinical-id"/>
            </observation>
          </component>
        </ClinicalDocument>
        """
    )

    metadata = _get_document_metadata(root)

    assert metadata == Document(
        documentId="document-id",
        versionNumber="7",
    )


def test_get_document_metadata_uses_empty_strings_for_missing_values():
    root = elem(f'<ClinicalDocument xmlns="{HL7_NS}"/>')

    metadata = _get_document_metadata(root)

    assert metadata == Document(documentId="", versionNumber="")


def test_process_additions_watch_list_emits_change_for_watched_descendant():
    root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <section>
              <observation ID="watched-observation"/>
            </section>
          </component>
        </ClinicalDocument>
        """
    )
    added_section = find_one(root, ".//hl7:section")
    watched_observation = find_one(added_section, ".//hl7:observation")

    changes = _process_additions(
        [added_section],
        DiffMode.WATCH_LIST,
        {watched_observation: rule()},
        Document(documentId="current-document-id", versionNumber="2"),
    )

    assert len(changes) == 1
    assert_change(
        changes[0],
        change_type=ChangeType.ADDED,
        node=added_section,
        document_id="current-document-id",
        rule_id=RULE_ID,
        rule_name=RULE_NAME,
    )


def test_process_additions_ignore_list_skips_directly_matched_element():
    root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <observation ID="ignored-addition"/>
          </component>
        </ClinicalDocument>
        """
    )
    ignored_addition = find_one(root, ".//hl7:observation")

    changes = _process_additions(
        [ignored_addition],
        DiffMode.IGNORE_LIST,
        {ignored_addition: rule()},
        Document(documentId="current-document-id", versionNumber="2"),
    )

    assert changes == []


def test_process_additions_ignore_list_skips_descendant_of_matched_element():
    root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <section ID="ignored-section">
              <observation ID="ignored-addition"/>
            </section>
            <section ID="included-section">
              <observation ID="included-addition"/>
            </section>
          </component>
        </ClinicalDocument>
        """
    )
    ignored_section = find_one(root, ".//hl7:section[@ID='ignored-section']")
    ignored_addition = find_one(root, ".//hl7:observation[@ID='ignored-addition']")
    included_addition = find_one(root, ".//hl7:observation[@ID='included-addition']")

    changes = _process_additions(
        [ignored_addition, included_addition],
        DiffMode.IGNORE_LIST,
        {ignored_section: rule()},
        Document(documentId="current-document-id", versionNumber="2"),
    )

    assert len(changes) == 1
    assert_change(
        changes[0],
        change_type=ChangeType.ADDED,
        node=included_addition,
        document_id="current-document-id",
        rule_id=DEFAULT_ACTIONABLE_RULE_ID,
        rule_name=DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME,
    )


def test_process_additions_ignore_list_includes_match_for_other_change_type():
    root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <observation ID="included-addition"/>
          </component>
        </ClinicalDocument>
        """
    )
    included_addition = find_one(root, ".//hl7:observation")

    changes = _process_additions(
        [included_addition],
        DiffMode.IGNORE_LIST,
        {
            included_addition: rule(
                change_types=frozenset({ChangeType.UPDATED}),
            )
        },
        Document(documentId="current-document-id", versionNumber="2"),
    )

    assert len(changes) == 1
    assert_change(
        changes[0],
        change_type=ChangeType.ADDED,
        node=included_addition,
        document_id="current-document-id",
        rule_id=DEFAULT_ACTIONABLE_RULE_ID,
        rule_name=DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME,
    )


def test_process_updates_watch_list_emits_change_for_direct_match():
    before_root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component><section><observation ID="result" value="old"/></section></component>
        </ClinicalDocument>
        """
    )
    after_root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component><section><observation ID="result" value="new"/></section></component>
        </ClinicalDocument>
        """
    )
    before = find_one(before_root, ".//hl7:observation")
    after = find_one(after_root, ".//hl7:observation")

    changes = _process_updates(
        [(before, after)],
        DiffMode.WATCH_LIST,
        {},
        {after: rule()},
        Document(documentId="current-document-id", versionNumber="2"),
    )

    assert len(changes) == 1
    assert_change(
        changes[0],
        change_type=ChangeType.UPDATED,
        node=after,
        document_id="current-document-id",
        rule_id=RULE_ID,
        rule_name=RULE_NAME,
    )


def test_process_updates_ignore_list_skips_matches_in_either_document():
    before_root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <section ID="ignored-before"><observation ID="one" value="old"/></section>
            <section ID="ignored-after"><observation ID="two" value="old"/></section>
            <section ID="included"><observation ID="three" value="old"/></section>
          </component>
        </ClinicalDocument>
        """
    )
    after_root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <section ID="ignored-before"><observation ID="one" value="new"/></section>
            <section ID="ignored-after"><observation ID="two" value="new"/></section>
            <section ID="included"><observation ID="three" value="new"/></section>
          </component>
        </ClinicalDocument>
        """
    )
    before_nodes = [
        find_one(before_root, f".//hl7:observation[@ID='{node_id}']")
        for node_id in ("one", "two", "three")
    ]
    after_nodes = [
        find_one(after_root, f".//hl7:observation[@ID='{node_id}']")
        for node_id in ("one", "two", "three")
    ]
    ignored_before = find_one(before_root, ".//hl7:section[@ID='ignored-before']")
    ignored_after = find_one(after_root, ".//hl7:section[@ID='ignored-after']")

    changes = _process_updates(
        list(zip(before_nodes, after_nodes, strict=True)),
        DiffMode.IGNORE_LIST,
        {ignored_before: rule()},
        {ignored_after: rule()},
        Document(documentId="current-document-id", versionNumber="2"),
    )

    assert len(changes) == 1
    assert_change(
        changes[0],
        change_type=ChangeType.UPDATED,
        node=after_nodes[2],
        document_id="current-document-id",
        rule_id=DEFAULT_ACTIONABLE_RULE_ID,
        rule_name=DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME,
    )


def test_process_deletions_watch_list_emits_change_for_watched_descendant():
    root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <section>
              <observation ID="watched-observation"/>
            </section>
          </component>
        </ClinicalDocument>
        """
    )
    deleted_section = find_one(root, ".//hl7:section")
    watched_observation = find_one(deleted_section, ".//hl7:observation")

    changes = _process_deletions(
        [deleted_section],
        DiffMode.WATCH_LIST,
        {watched_observation: rule()},
        Document(documentId="previous-document-id", versionNumber="1"),
    )

    assert len(changes) == 1
    assert_change(
        changes[0],
        change_type=ChangeType.DELETED,
        node=deleted_section,
        document_id="previous-document-id",
        rule_id=RULE_ID,
        rule_name=RULE_NAME,
    )


def test_process_deletions_ignore_list_skips_ignored_ancestry():
    root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component>
            <section ID="ignored-section">
              <observation ID="ignored-deletion"/>
            </section>
            <section ID="included-section">
              <observation ID="included-deletion"/>
            </section>
          </component>
        </ClinicalDocument>
        """
    )
    ignored_section = find_one(root, ".//hl7:section[@ID='ignored-section']")
    ignored_deletion = find_one(root, ".//hl7:observation[@ID='ignored-deletion']")
    included_deletion = find_one(root, ".//hl7:observation[@ID='included-deletion']")

    changes = _process_deletions(
        [ignored_deletion, included_deletion],
        DiffMode.IGNORE_LIST,
        {ignored_section: rule()},
        Document(documentId="previous-document-id", versionNumber="1"),
    )

    assert len(changes) == 1
    assert_change(
        changes[0],
        change_type=ChangeType.DELETED,
        node=included_deletion,
        document_id="previous-document-id",
        rule_id=DEFAULT_ACTIONABLE_RULE_ID,
        rule_name=DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME,
    )


def test_unique_rule_matches_keeps_one_match_per_rule():
    entry = elem(
        f"""
        <entry xmlns="{HL7_NS}">
          <observation>
            <id root="example"/>
          </observation>
        </entry>
        """
    )
    rule = Rule(
        displayName="Entry",
        changeTypes={
            ChangeType.ADDED,
            ChangeType.UPDATED,
            ChangeType.DELETED,
        },
        xpaths=["//hl7:entry/descendant-or-self::*"],
    )
    rule_match_cache = build_rule_match_cache(entry.getroottree(), [rule])
    observation = find_one(entry, "./hl7:observation")
    identifier = find_one(observation, "./hl7:id")

    added_or_deleted_matches = rule_matches_for_node_and_descendants(
        observation,
        rule_match_cache,
    )
    assert added_or_deleted_matches[0] is rule_match_cache[observation]
    assert added_or_deleted_matches[1] is rule_match_cache[identifier]
    assert unique_rule_matches(
        added_or_deleted_matches,
        ChangeType.ADDED,
    ) == [added_or_deleted_matches[0]]

    updated_matches = rule_matches_for_node_and_ancestors(
        identifier,
        rule_match_cache,
    )
    assert updated_matches[0] is rule_match_cache[identifier]
    assert updated_matches[1] is rule_match_cache[observation]
    assert updated_matches[2] is rule_match_cache[entry]
    assert unique_rule_matches(updated_matches, ChangeType.UPDATED) == [
        updated_matches[0]
    ]


def test_unique_rule_matches_filters_by_change_type():
    entry = elem(
        f"""
        <entry xmlns="{HL7_NS}">
          <observation/>
        </entry>
        """
    )
    added_rule = Rule(
        displayName="Added entries",
        changeTypes={ChangeType.ADDED},
        xpaths=["//hl7:entry/descendant-or-self::*"],
    )
    rule_match_cache = build_rule_match_cache(entry.getroottree(), [added_rule])
    observation = find_one(entry, "./hl7:observation")
    matches = rule_matches_for_node_and_ancestors(observation, rule_match_cache)

    assert unique_rule_matches(matches, ChangeType.ADDED) == [matches[0]]
    assert unique_rule_matches(matches, ChangeType.UPDATED) == []
    assert unique_rule_matches(matches, ChangeType.DELETED) == []
    assert change_is_ignorable(matches, ChangeType.ADDED)
    assert not change_is_ignorable(matches, ChangeType.UPDATED)


def test_rule_requires_at_least_one_change_type():
    with pytest.raises(ValidationError):
        Rule(
            displayName="Invalid rule",
            changeTypes=set(),
        )
