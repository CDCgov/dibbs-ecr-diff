import pytest
from core import (
    build_cache,
    cached_ancestry,
    cached_subtree,
    change_is_not_ignorable,
    unique_rule_matches,
)
from core.models import ChangeType, RuleConfig
from helpers import HL7_NS, elem, find_one
from pydantic import ValidationError


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
    rule = RuleConfig(
        displayName="Entry",
        changeTypes={
            ChangeType.ADDED,
            ChangeType.UPDATED,
            ChangeType.DELETED,
        },
        xpaths=["//hl7:entry/descendant-or-self::*"],
    )
    cache = build_cache(entry.getroottree(), [rule])
    observation = find_one(entry, "./hl7:observation")
    identifier = find_one(observation, "./hl7:id")

    added_or_deleted_matches = cached_subtree(observation, cache)
    assert [match.node for match in added_or_deleted_matches] == [
        observation,
        identifier,
    ]
    assert unique_rule_matches(
        added_or_deleted_matches,
        ChangeType.ADDED,
    ) == [added_or_deleted_matches[0]]

    updated_matches = cached_ancestry(identifier, cache)
    assert [match.node for match in updated_matches] == [
        identifier,
        observation,
        entry,
    ]
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
    added_rule = RuleConfig(
        displayName="Added entries",
        changeTypes={ChangeType.ADDED},
        xpaths=["//hl7:entry/descendant-or-self::*"],
    )
    cache = build_cache(entry.getroottree(), [added_rule])
    observation = find_one(entry, "./hl7:observation")
    matches = cached_ancestry(observation, cache)

    assert unique_rule_matches(matches, ChangeType.ADDED) == [matches[0]]
    assert unique_rule_matches(matches, ChangeType.UPDATED) == []
    assert unique_rule_matches(matches, ChangeType.DELETED) == []
    assert not change_is_not_ignorable(matches, ChangeType.ADDED)
    assert change_is_not_ignorable(matches, ChangeType.UPDATED)


def test_rule_config_requires_at_least_one_change_type():
    with pytest.raises(ValidationError):
        RuleConfig(
            displayName="Invalid rule",
            changeTypes=set(),
        )
