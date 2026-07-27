from core import (
    build_cache,
    cached_ancestry,
    cached_subtree,
    unique_rule_matches,
)
from core.models import RuleConfig
from helpers import HL7_NS, elem, find_one


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
    assert unique_rule_matches(added_or_deleted_matches) == [
        added_or_deleted_matches[0]
    ]

    updated_matches = cached_ancestry(identifier, cache)
    assert [match.node for match in updated_matches] == [
        identifier,
        observation,
        entry,
    ]
    assert unique_rule_matches(updated_matches) == [
        updated_matches[0]
    ]
