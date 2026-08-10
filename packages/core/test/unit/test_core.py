import json
from uuid import UUID

import pytest
from core import (
    _get_document_metadata,
    _process_additions,
    _process_deletions,
    _process_updates,
    _section_loinc_code_for_change,
    build_rule_match_cache,
    rule_matches_for_node_and_ancestors,
    rule_matches_for_node_and_descendants,
    unique_rule_matches_for_change_type,
)
from core.constants import (
    DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME,
    DEFAULT_ACTIONABLE_RULE_ID,
)
from core.models import Change, ChangeType, DiffMode, Document, Rule
from core.paths import structural_xpath
from helpers import HL7_NS, elem, find_one
from lxml import etree
from pydantic import ValidationError

RULE_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
RULE_NAME = "Relevant clinical observation"
SECOND_RULE_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
SECOND_RULE_NAME = "Second relevant clinical observation"


def make_rule(
    change_types: set[ChangeType] | None = None,
    rule_id: UUID = RULE_ID,
    rule_name: str = RULE_NAME,
) -> Rule:
    if change_types is None:
        change_types = {
            ChangeType.ADDED,
            ChangeType.UPDATED,
            ChangeType.DELETED,
        }
    return Rule(
        id=rule_id,
        displayName=rule_name,
        changeTypes=change_types,
    )


def assert_change(
    change: Change,
    *,
    change_type: ChangeType,
    node: etree._Element,
    document_id: str,
    is_actionable: bool,
    rule_id: UUID | None = None,
    rule_name: str | None = None,
) -> None:
    assert change.changeType == change_type
    assert change.xpath == structural_xpath(node)
    assert change.xpathDocumentId == document_id
    assert change.isActionable is is_actionable
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


@pytest.mark.parametrize(
    ("xml", "expected"),
    [
        (
            f"""
            <section xmlns="{HL7_NS}">
              <code code="10160-0" codeSystem="2.16.840.1.113883.6.1"/>
              <component>
                <section>
                  <code code="18776-5" codeSystem="2.16.840.1.113883.6.1"/>
                  <entry>
                    <observation>
                      <code code="718-7" codeSystem="2.16.840.1.113883.6.1"/>
                      <value ID="target"/>
                    </observation>
                  </entry>
                </section>
              </component>
            </section>
            """,
            "18776-5",
        ),
        (
            f"""
            <ClinicalDocument xmlns="{HL7_NS}">
              <component>
                <section ID="target">
                  <code code="18776-5" codeSystem="2.16.840.1.113883.6.1"/>
                </section>
              </component>
            </ClinicalDocument>
            """,
            "18776-5",
        ),
        (
            f"""
            <ClinicalDocument xmlns="{HL7_NS}">
              <recordTarget ID="target"/>
            </ClinicalDocument>
            """,
            None,
        ),
        (
            f"""
            <section xmlns="{HL7_NS}">
              <code code="365860008" codeSystem="2.16.840.1.113883.6.96"/>
              <observation>
                <code code="718-7" codeSystem="2.16.840.1.113883.6.1"/>
                <value ID="target"/>
              </observation>
            </section>
            """,
            None,
        ),
        (
            f"""
            <section xmlns="{HL7_NS}">
              <code code="not-a-loinc-code"
                    codeSystem="2.16.840.1.113883.6.1"/>
              <value ID="target"/>
            </section>
            """,
            None,
        ),
    ],
)
def test_section_loinc_code_uses_only_nearest_enclosing_section(
    xml: str,
    expected: str | None,
) -> None:
    root = elem(xml)
    changed_element = find_one(root, ".//*[@ID='target']")

    assert _section_loinc_code_for_change(changed_element) == expected


def test_all_change_types_capture_loinc_without_serializing_it() -> None:
    previous_root = elem(
        f"""
        <section xmlns="{HL7_NS}">
          <code code="10160-0" codeSystem="2.16.840.1.113883.6.1"/>
          <observation ID="target" value="old"/>
        </section>
        """
    )
    current_root = elem(
        f"""
        <section xmlns="{HL7_NS}">
          <code code="18776-5" codeSystem="2.16.840.1.113883.6.1"/>
          <observation ID="target" value="new"/>
        </section>
        """
    )
    previous = find_one(previous_root, "./hl7:observation")
    current = find_one(current_root, "./hl7:observation")
    previous_document = Document(documentId="previous-document-id", versionNumber="1")
    current_document = Document(documentId="current-document-id", versionNumber="2")

    added_change = _process_additions(
        [current], DiffMode.IGNORE_LIST, {}, current_document
    )[0]
    updated_change = _process_updates(
        [(previous, current)], DiffMode.IGNORE_LIST, {}, {}, current_document
    )[0]
    deleted_change = _process_deletions(
        [previous], DiffMode.IGNORE_LIST, {}, previous_document
    )[0]

    assert added_change.section_loinc_code == "18776-5"
    assert updated_change.section_loinc_code == "18776-5"
    assert deleted_change.section_loinc_code == "10160-0"
    assert (
        "section_loinc_code"
        not in Change.model_json_schema(mode="serialization")["properties"]
    )
    for change in (added_change, updated_change, deleted_change):
        assert "section_loinc_code" not in change.model_dump()
        assert '"section_loinc_code"' not in change.model_dump_json()


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
        added=[added_section],
        mode=DiffMode.WATCH_LIST,
        right_rule_match_cache={watched_observation: [make_rule()]},
        current_document=Document(documentId="current-document-id", versionNumber="2"),
    )

    assert len(changes) == 1
    assert_change(
        changes[0],
        change_type=ChangeType.ADDED,
        node=added_section,
        document_id="current-document-id",
        is_actionable=True,
        rule_id=RULE_ID,
        rule_name=RULE_NAME,
    )


def test_process_additions_watch_list_uses_only_rules_applicable_to_additions():
    root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component><observation ID="watched-addition"/></component>
        </ClinicalDocument>
        """
    )
    added_observation = find_one(root, ".//hl7:observation")
    added_rule = Rule(
        id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        displayName="Added observations",
        changeTypes={ChangeType.ADDED},
        xpaths=["//hl7:observation"],
    )
    updated_rule = Rule(
        id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        displayName="Updated observations",
        changeTypes={ChangeType.UPDATED},
        xpaths=["//hl7:observation"],
    )
    rule_match_cache = build_rule_match_cache(
        root.getroottree(),
        [added_rule, updated_rule],
    )

    changes = _process_additions(
        added=[added_observation],
        mode=DiffMode.WATCH_LIST,
        right_rule_match_cache=rule_match_cache,
        current_document=Document(documentId="current-document-id", versionNumber="2"),
    )

    assert rule_match_cache[added_observation] == [added_rule, updated_rule]
    assert len(changes) == 1
    assert_change(
        changes[0],
        change_type=ChangeType.ADDED,
        node=added_observation,
        document_id="current-document-id",
        is_actionable=True,
        rule_id=added_rule.id,
        rule_name=added_rule.displayName,
    )


def test_process_additions_watch_list_emits_once_per_applicable_rule():
    root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component><observation ID="watched-addition"/></component>
        </ClinicalDocument>
        """
    )
    added_observation = find_one(root, ".//hl7:observation")
    first_rule = Rule(
        id=UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"),
        displayName="First added-observation rule",
        changeTypes={ChangeType.ADDED},
        xpaths=["//hl7:observation"],
    )
    second_rule = Rule(
        id=UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"),
        displayName="Second added-observation rule",
        changeTypes={ChangeType.ADDED},
        xpaths=["//hl7:observation"],
    )
    rule_match_cache = build_rule_match_cache(
        root.getroottree(),
        [first_rule, second_rule],
    )

    changes = _process_additions(
        added=[added_observation],
        mode=DiffMode.WATCH_LIST,
        right_rule_match_cache=rule_match_cache,
        current_document=Document(documentId="current-document-id", versionNumber="2"),
    )

    assert len(changes) == 2
    for change, matching_rule in zip(
        changes,
        [first_rule, second_rule],
        strict=True,
    ):
        assert_change(
            change,
            change_type=ChangeType.ADDED,
            node=added_observation,
            document_id="current-document-id",
            is_actionable=True,
            rule_id=matching_rule.id,
            rule_name=matching_rule.displayName,
        )


def test_process_additions_watch_list_retains_unmatched_change():
    root = elem(
        f'<ClinicalDocument xmlns="{HL7_NS}"><component><observation/></component></ClinicalDocument>'
    )
    added_observation = find_one(root, ".//hl7:observation")

    changes = _process_additions(
        added=[added_observation],
        mode=DiffMode.WATCH_LIST,
        right_rule_match_cache={},
        current_document=Document(documentId="current-document-id", versionNumber="2"),
    )

    assert len(changes) == 1
    assert_change(
        changes[0],
        change_type=ChangeType.ADDED,
        node=added_observation,
        document_id="current-document-id",
        is_actionable=False,
    )


def test_process_additions_ignore_list_retains_direct_match_as_nonactionable():
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
        added=[ignored_addition],
        mode=DiffMode.IGNORE_LIST,
        right_rule_match_cache={
            ignored_addition: [
                make_rule(),
                make_rule(rule_id=SECOND_RULE_ID, rule_name=SECOND_RULE_NAME),
            ]
        },
        current_document=Document(documentId="current-document-id", versionNumber="2"),
    )

    assert len(changes) == 2
    for change, rule_id, rule_name in zip(
        changes,
        (RULE_ID, SECOND_RULE_ID),
        (RULE_NAME, SECOND_RULE_NAME),
        strict=True,
    ):
        assert_change(
            change,
            change_type=ChangeType.ADDED,
            node=ignored_addition,
            document_id="current-document-id",
            is_actionable=False,
            rule_id=rule_id,
            rule_name=rule_name,
        )


def test_process_additions_ignore_list_retains_ignored_descendant():
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
        added=[ignored_addition, included_addition],
        mode=DiffMode.IGNORE_LIST,
        right_rule_match_cache={ignored_section: [make_rule()]},
        current_document=Document(documentId="current-document-id", versionNumber="2"),
    )

    assert len(changes) == 2
    assert_change(
        changes[0],
        change_type=ChangeType.ADDED,
        node=ignored_addition,
        document_id="current-document-id",
        is_actionable=False,
        rule_id=RULE_ID,
        rule_name=RULE_NAME,
    )
    assert_change(
        changes[1],
        change_type=ChangeType.ADDED,
        node=included_addition,
        document_id="current-document-id",
        is_actionable=True,
        rule_id=DEFAULT_ACTIONABLE_RULE_ID,
        rule_name=DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME,
    )


def test_process_additions_ignore_list_treats_inapplicable_rule_as_unmatched():
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
        added=[included_addition],
        mode=DiffMode.IGNORE_LIST,
        right_rule_match_cache={
            included_addition: [
                make_rule(
                    change_types={ChangeType.UPDATED},
                )
            ]
        },
        current_document=Document(documentId="current-document-id", versionNumber="2"),
    )

    assert len(changes) == 1
    assert_change(
        changes[0],
        change_type=ChangeType.ADDED,
        node=included_addition,
        document_id="current-document-id",
        is_actionable=True,
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
        updated=[(before, after)],
        mode=DiffMode.WATCH_LIST,
        left_rule_match_cache={},
        right_rule_match_cache={after: [make_rule()]},
        current_document=Document(documentId="current-document-id", versionNumber="2"),
    )

    assert len(changes) == 1
    assert_change(
        changes[0],
        change_type=ChangeType.UPDATED,
        node=after,
        document_id="current-document-id",
        is_actionable=True,
        rule_id=RULE_ID,
        rule_name=RULE_NAME,
    )


def test_process_updates_watch_list_retains_unmatched_change():
    before = elem(f'<observation xmlns="{HL7_NS}" value="old"/>')
    after = elem(f'<observation xmlns="{HL7_NS}" value="new"/>')

    changes = _process_updates(
        updated=[(before, after)],
        mode=DiffMode.WATCH_LIST,
        left_rule_match_cache={},
        right_rule_match_cache={},
        current_document=Document(documentId="current-document-id", versionNumber="2"),
    )

    assert len(changes) == 1
    assert_change(
        changes[0],
        change_type=ChangeType.UPDATED,
        node=after,
        document_id="current-document-id",
        is_actionable=False,
    )


def test_process_updates_ignore_list_retains_matches_as_nonactionable():
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
        updated=list(zip(before_nodes, after_nodes, strict=True)),
        mode=DiffMode.IGNORE_LIST,
        left_rule_match_cache={
            ignored_before: [
                make_rule(),
                make_rule(rule_id=SECOND_RULE_ID, rule_name=SECOND_RULE_NAME),
            ]
        },
        right_rule_match_cache={ignored_after: [make_rule()]},
        current_document=Document(documentId="current-document-id", versionNumber="2"),
    )

    assert len(changes) == 4
    for change, rule_id, rule_name in zip(
        changes[:2],
        (RULE_ID, SECOND_RULE_ID),
        (RULE_NAME, SECOND_RULE_NAME),
        strict=True,
    ):
        assert_change(
            change,
            change_type=ChangeType.UPDATED,
            node=after_nodes[0],
            document_id="current-document-id",
            is_actionable=False,
            rule_id=rule_id,
            rule_name=rule_name,
        )
    assert_change(
        changes[2],
        change_type=ChangeType.UPDATED,
        node=after_nodes[1],
        document_id="current-document-id",
        is_actionable=False,
        rule_id=RULE_ID,
        rule_name=RULE_NAME,
    )
    assert_change(
        changes[3],
        change_type=ChangeType.UPDATED,
        node=after_nodes[2],
        document_id="current-document-id",
        is_actionable=True,
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
        deleted=[deleted_section],
        mode=DiffMode.WATCH_LIST,
        left_rule_match_cache={watched_observation: [make_rule()]},
        previous_document=Document(
            documentId="previous-document-id", versionNumber="1"
        ),
    )

    assert len(changes) == 1
    assert_change(
        changes[0],
        change_type=ChangeType.DELETED,
        node=deleted_section,
        document_id="previous-document-id",
        is_actionable=True,
        rule_id=RULE_ID,
        rule_name=RULE_NAME,
    )


def test_process_deletions_watch_list_retains_unmatched_change():
    root = elem(
        f'<ClinicalDocument xmlns="{HL7_NS}"><component><observation/></component></ClinicalDocument>'
    )
    deleted_observation = find_one(root, ".//hl7:observation")

    changes = _process_deletions(
        deleted=[deleted_observation],
        mode=DiffMode.WATCH_LIST,
        left_rule_match_cache={},
        previous_document=Document(
            documentId="previous-document-id", versionNumber="1"
        ),
    )

    assert len(changes) == 1
    assert_change(
        changes[0],
        change_type=ChangeType.DELETED,
        node=deleted_observation,
        document_id="previous-document-id",
        is_actionable=False,
    )


def test_process_deletions_ignore_list_retains_ignored_ancestry():
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
        deleted=[ignored_deletion, included_deletion],
        mode=DiffMode.IGNORE_LIST,
        left_rule_match_cache={
            ignored_section: [
                make_rule(),
                make_rule(rule_id=SECOND_RULE_ID, rule_name=SECOND_RULE_NAME),
            ]
        },
        previous_document=Document(
            documentId="previous-document-id", versionNumber="1"
        ),
    )

    assert len(changes) == 3
    for change, rule_id, rule_name in zip(
        changes[:2],
        (RULE_ID, SECOND_RULE_ID),
        (RULE_NAME, SECOND_RULE_NAME),
        strict=True,
    ):
        assert_change(
            change,
            change_type=ChangeType.DELETED,
            node=ignored_deletion,
            document_id="previous-document-id",
            is_actionable=False,
            rule_id=rule_id,
            rule_name=rule_name,
        )
    assert_change(
        changes[2],
        change_type=ChangeType.DELETED,
        node=included_deletion,
        document_id="previous-document-id",
        is_actionable=True,
        rule_id=DEFAULT_ACTIONABLE_RULE_ID,
        rule_name=DEFAULT_ACTIONABLE_RULE_DISPLAY_NAME,
    )


def test_build_rule_match_cache_stores_rule_once_when_xpaths_overlap():
    root = elem(
        f"""
        <ClinicalDocument xmlns="{HL7_NS}">
          <component><observation ID="watched-observation"/></component>
        </ClinicalDocument>
        """
    )
    observation = find_one(root, ".//hl7:observation")
    matching_rule = Rule(
        displayName="Overlapping observation XPaths",
        changeTypes={ChangeType.ADDED},
        xpaths=[
            "//hl7:observation",
            "//*[@ID='watched-observation']",
        ],
    )

    rule_match_cache = build_rule_match_cache(
        root.getroottree(),
        [matching_rule],
    )

    assert rule_match_cache[observation] == [matching_rule]


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
    entry_rule = Rule(
        displayName="Entry",
        changeTypes={
            ChangeType.ADDED,
            ChangeType.UPDATED,
            ChangeType.DELETED,
        },
        xpaths=["//hl7:entry/descendant-or-self::*"],
    )
    rule_match_cache = build_rule_match_cache(entry.getroottree(), [entry_rule])
    observation = find_one(entry, "./hl7:observation")
    identifier = find_one(observation, "./hl7:id")

    added_or_deleted_matches = rule_matches_for_node_and_descendants(
        observation,
        rule_match_cache,
    )
    assert added_or_deleted_matches[0] is rule_match_cache[observation][0]
    assert added_or_deleted_matches[1] is rule_match_cache[identifier][0]
    assert unique_rule_matches_for_change_type(
        added_or_deleted_matches,
        ChangeType.ADDED,
    ) == [added_or_deleted_matches[0]]

    updated_matches = rule_matches_for_node_and_ancestors(
        identifier,
        rule_match_cache,
    )
    assert updated_matches[0] is rule_match_cache[identifier][0]
    assert updated_matches[1] is rule_match_cache[observation][0]
    assert updated_matches[2] is rule_match_cache[entry][0]
    assert unique_rule_matches_for_change_type(updated_matches, ChangeType.UPDATED) == [
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

    assert unique_rule_matches_for_change_type(matches, ChangeType.ADDED) == [
        matches[0]
    ]
    assert unique_rule_matches_for_change_type(matches, ChangeType.UPDATED) == []
    assert unique_rule_matches_for_change_type(matches, ChangeType.DELETED) == []


def test_rule_requires_at_least_one_change_type():
    with pytest.raises(ValidationError):
        Rule(
            displayName="Invalid rule",
            changeTypes=set(),
        )


def test_nonactionable_change_serializes_missing_rule_fields_as_null():
    change = Change(
        changeType=ChangeType.UPDATED,
        xpath="/hl7:ClinicalDocument[1]",
        xpathDocumentId="current-document-id",
        isActionable=False,
    )

    serialized_change = json.loads(change.model_dump_json())

    assert serialized_change["actionabilityRuleId"] is None
    assert serialized_change["actionabilityRuleDisplayName"] is None
