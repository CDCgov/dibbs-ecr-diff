"""
core/matching.py

Child element matching machinery.

Responsible for pairing elements from a before-tree sibling list against
elements from the corresponding after-tree sibling list, yielding (e1, e2)
pairs where either side may be None to indicate an addition or deletion.

Prefer-updates pairing is always active: when multiple elements share the
same templateId, the soft context key is used to preferentially pair them
as updates rather than add+delete pairs.

When exact stable keys differ, overlap pairing can still preserve continuity
for unambiguous alternate child IDs, wrappers whose nested section ID set only
changed by additions or deletions, and templateId sets that changed only by
adding or removing conformance identities.
"""

from collections import defaultdict
from typing import Dict, List, Tuple, cast

from lxml import etree

import core.config as _cfg
from core.cda_identity import (
    RootExtensionIdentity,
    RootExtensionSetKey,
    RootExtensionSetSource,
    StableKey,
    narrative_row_key,
    narrative_table_key,
    secondary_discriminator,
    soft_context_key,
    stable_key,
)
from core.xml_utils import localname

ID_STABLE_KEY_SOURCES = frozenset({
    RootExtensionSetSource.DIRECT_IDS,
    RootExtensionSetSource.NESTED_STATEMENT_IDS,
})
SECTION_ID_STABLE_KEY_SOURCES = frozenset({
    RootExtensionSetSource.NESTED_SECTION_IDS,
})
TEMPLATE_ID_STABLE_KEY_SOURCES = (
    RootExtensionSetSource.DIRECT_TEMPLATE_IDS,
    RootExtensionSetSource.NESTED_SECTION_TEMPLATE_IDS,
    RootExtensionSetSource.NESTED_STATEMENT_TEMPLATE_IDS,
)

# ---------------------------------------------------------------------------
# Child grouping
# ---------------------------------------------------------------------------

def build_child_groups(parent: etree._Element) -> Dict[str, List[etree._Element]]:
    """
    Group the immediate element children of `parent` by tag name.

    Namespaced tags use Clark notation (`{namespace}localname`);
    unnamespaced tags are plain names.
    """
    groups: Dict[str, List[etree._Element]] = defaultdict(list)
    for child in parent.iterchildren(tag=etree.Element):
        if not isinstance(child.tag, str):
            continue
        groups[child.tag].append(child)
    return groups


# ---------------------------------------------------------------------------
# Prefer-updates soft pairing
# ---------------------------------------------------------------------------

def _is_table_cell_list(elements: List[etree._Element]) -> bool:
    """Return True if every element in the list is a <td> or <th>."""
    return bool(elements) and all(localname(elem) in ("td", "th") for elem in elements)


def _prefer_updates_pairing(
        before_list: List[etree._Element],
        after_list: List[etree._Element],
) -> Tuple[List[Tuple], List[etree._Element], List[etree._Element]]:
    """
    Attempt to pair elements from before_list and after_list by their soft
    context key, preferring to classify matching elements as updates rather
    than add+delete pairs.

    Returns (matched_pairs, unmatched_from_before, unmatched_from_after).
    Elements whose soft context key is None are left unmatched.
    """
    before_buckets: Dict = defaultdict(list)
    after_buckets:  Dict = defaultdict(list)
    for elem in before_list:
        before_buckets[soft_context_key(elem)].append(elem)
    for elem in after_list:
        after_buckets[soft_context_key(elem)].append(elem)

    matched_pairs = []
    unmatched_before = []
    unmatched_after  = []

    all_keys = sorted(
        (set(before_buckets) | set(after_buckets)) - {None}, key=str
    )

    for key in all_keys:
        before_group = before_buckets.get(key, [])
        after_group  = after_buckets.get(key, [])
        pair_count   = min(len(before_group), len(after_group))
        for index in range(pair_count):
            matched_pairs.append((before_group[index], after_group[index]))
            #replace the below line with python's logging library
            _cfg.debug_log(f"[soft-pair] key={key}")
        unmatched_before.extend(before_group[pair_count:])
        unmatched_after.extend(after_group[pair_count:])

    unmatched_before.extend(before_buckets.get(None, []))
    unmatched_after.extend(after_buckets.get(None, []))
    return matched_pairs, unmatched_before, unmatched_after


def _root_extension_identities_from_stable_key(
        stable_key_value: StableKey | None,
        allowed_sources: frozenset[RootExtensionSetSource],
) -> tuple[RootExtensionIdentity, ...]:
    """Return root/extension identities from allowed stable_key variants."""
    if not isinstance(stable_key_value, RootExtensionSetKey):
        return ()

    if stable_key_value.source not in allowed_sources:
        return ()

    return stable_key_value.identities


def _index_elements_by_identity(
        elements: List[etree._Element],
        allowed_sources: frozenset[RootExtensionSetSource],
) -> tuple[
    Dict[RootExtensionIdentity, List[etree._Element]],
    Dict[int, tuple[RootExtensionIdentity, ...]],
    Dict[int, etree._Element],
]:
    """Index elements by each allowed root/extension identity they contain."""
    elements_by_identity: Dict[
        RootExtensionIdentity,
        List[etree._Element],
    ] = defaultdict(list)
    identities_by_element_id: Dict[int, tuple[RootExtensionIdentity, ...]] = {}
    elements_by_id: Dict[int, etree._Element] = {}

    for elem in elements:
        identities = _root_extension_identities_from_stable_key(
            stable_key(elem),
            allowed_sources,
        )
        if not identities:
            continue

        elem_id = id(elem)
        identities_by_element_id[elem_id] = identities
        elements_by_id[elem_id] = elem

        for identity in identities:
            elements_by_identity[identity].append(elem)

    return elements_by_identity, identities_by_element_id, elements_by_id


def _shared_identity_pairing(
        before_list: List[etree._Element],
        after_list: List[etree._Element],
        allowed_sources: frozenset[RootExtensionSetSource],
        require_complete_subset: bool = False,
) -> Tuple[List[Tuple], List[etree._Element], List[etree._Element]]:
    """
    Pair elements that share unambiguous root/extension identities.

    An identity is usable only if it maps to exactly one before element and one
    after element. A candidate pair is accepted only when each side has a single
    possible counterpart. When require_complete_subset is true, every identity
    from the smaller identity set must be shared by the larger set.
    """
    before_by_identity, before_identities_by_id, before_elements_by_id = (
        _index_elements_by_identity(before_list, allowed_sources)
    )
    after_by_identity, after_identities_by_id, after_elements_by_id = (
        _index_elements_by_identity(after_list, allowed_sources)
    )

    candidate_shared_ids: Dict[
        tuple[int, int],
        set[RootExtensionIdentity],
    ] = defaultdict(set)
    before_candidate_after_ids: Dict[int, set[int]] = defaultdict(set)
    after_candidate_before_ids: Dict[int, set[int]] = defaultdict(set)

    shared_identities: set[RootExtensionIdentity] = set(
        before_by_identity.keys(),
    ) & set(after_by_identity.keys())
    sorted_shared_identities = cast(
        list[RootExtensionIdentity],
        sorted(shared_identities, key=str),
    )
    for identity in sorted_shared_identities:
        before_group = before_by_identity[identity]
        after_group = after_by_identity[identity]
        if len(before_group) != 1 or len(after_group) != 1:
            continue

        before_elem = before_group[0]
        after_elem = after_group[0]
        before_id = id(before_elem)
        after_id = id(after_elem)

        candidate_shared_ids[(before_id, after_id)].add(identity)
        before_candidate_after_ids[before_id].add(after_id)
        after_candidate_before_ids[after_id].add(before_id)

    matched_pairs = []
    paired_before_ids = set()
    paired_after_ids = set()

    def _candidate_sort_key(
            candidate: tuple[tuple[int, int], set[RootExtensionIdentity]],
    ) -> str:
        return str(tuple(sorted(candidate[1])))

    for pair_key, _ in sorted(
            candidate_shared_ids.items(),
            key=_candidate_sort_key,
    ):
        before_id, after_id = pair_key

        if len(before_candidate_after_ids[before_id]) != 1:
            continue
        if len(after_candidate_before_ids[after_id]) != 1:
            continue
        if before_id in paired_before_ids or after_id in paired_after_ids:
            continue
        if require_complete_subset:
            before_identities = set(before_identities_by_id[before_id])
            after_identities = set(after_identities_by_id[after_id])
            shared_identities_for_pair = candidate_shared_ids[pair_key]
            smaller_identity_set_size = min(
                len(before_identities),
                len(after_identities),
            )
            if len(shared_identities_for_pair) != smaller_identity_set_size:
                continue

        matched_pairs.append((
            before_elements_by_id[before_id],
            after_elements_by_id[after_id],
        ))
        paired_before_ids.add(before_id)
        paired_after_ids.add(after_id)

    unmatched_before = [
        elem for elem in before_list if id(elem) not in paired_before_ids
    ]
    unmatched_after = [
        elem for elem in after_list if id(elem) not in paired_after_ids
    ]

    return matched_pairs, unmatched_before, unmatched_after


def _shared_child_id_pairing(
        before_list: List[etree._Element],
        after_list: List[etree._Element],
) -> Tuple[List[Tuple], List[etree._Element], List[etree._Element]]:
    """
    Pair elements that share unambiguous CDA child-id identities.

    This treats repeated CDA <id> values as alternate identities without
    requiring the full child-id sets to match exactly.
    """
    return _shared_identity_pairing(
        before_list,
        after_list,
        ID_STABLE_KEY_SOURCES,
    )


def _shared_nested_section_id_pairing(
        before_list: List[etree._Element],
        after_list: List[etree._Element],
) -> Tuple[List[Tuple], List[etree._Element], List[etree._Element]]:
    """
    Pair wrappers that share an unambiguous nested-section ID subset.

    This preserves wrapper continuity when sections are added or deleted, but
    only if all section IDs from the smaller wrapper are present in the larger
    wrapper.
    """
    return _shared_identity_pairing(
        before_list,
        after_list,
        SECTION_ID_STABLE_KEY_SOURCES,
        require_complete_subset=True,
    )


def _shared_template_id_pairing(
        before_list: List[etree._Element],
        after_list: List[etree._Element],
) -> Tuple[List[Tuple], List[etree._Element], List[etree._Element]]:
    """
    Pair elements that share an unambiguous templateId subset.

    Template IDs identify CDA conformance/type rather than a specific instance,
    so this fallback is weaker than ID-based matching. Each stable-key kind is
    matched separately by source so direct templateId keys do not pair with
    nested section or nested statement templateId keys.
    """
    matched_pairs = []

    for source in TEMPLATE_ID_STABLE_KEY_SOURCES:
        template_id_pairs, before_list, after_list = _shared_identity_pairing(
            before_list,
            after_list,
            frozenset({source}),
            require_complete_subset=True,
        )
        matched_pairs.extend(template_id_pairs)

    return matched_pairs, before_list, after_list


def _stable_key_overlap_pairing(
        before_list: List[etree._Element],
        after_list: List[etree._Element],
) -> Tuple[List[Tuple], List[etree._Element], List[etree._Element]]:
    """
    Apply overlap fallbacks from strongest to weakest stable-key identity.

    Child IDs are more specific than nested section IDs, and both are stronger
    than template IDs. TemplateId overlap is tried last because it represents
    conformance/type continuity rather than instance identity.
    """
    matched_pairs = []

    child_id_pairs, before_list, after_list = _shared_child_id_pairing(
        before_list,
        after_list,
    )
    matched_pairs.extend(child_id_pairs)

    section_id_pairs, before_list, after_list = (
        _shared_nested_section_id_pairing(before_list, after_list)
    )
    matched_pairs.extend(section_id_pairs)

    template_id_pairs, before_list, after_list = _shared_template_id_pairing(
        before_list,
        after_list,
    )
    matched_pairs.extend(template_id_pairs)

    return matched_pairs, before_list, after_list


# ---------------------------------------------------------------------------
# Main matching entry point
# ---------------------------------------------------------------------------

def match_children_ignore_order(
        before_list: List[etree._Element],
        after_list: List[etree._Element],
):
    """
    Yield (before_elem, after_elem) pairs matching elements from before_list
    against after_list.  Either side of a pair may be None, indicating an
    addition (None, after_elem) or deletion (before_elem, None).

    Matching strategy (applied in order):
      1. Table cells (<td>/<th>) — paired by column position
      2. Unique stable keys on both sides — direct dictionary lookup
         2a. Unmatched CDA child-id keys may pair by unambiguous ID overlap
         2b. Unmatched nested-section ID keys may pair when one ID set is a
             complete subset of the other
         2c. Unmatched templateId keys may pair when one templateId set is a
             complete subset of the other
      3. Primary bucket by narrative key / stable key / tag
         3a. Within templateId.identities buckets, apply prefer-updates soft pairing
         3b. Within remaining buckets, use secondary discriminator matching
    """
    # --- Strategy 1: column-positional pairing for table cells ---
    if _is_table_cell_list(before_list) and _is_table_cell_list(after_list):
        pair_count = min(len(before_list), len(after_list))
        for index in range(pair_count):
            yield before_list[index], after_list[index]
        for index in range(pair_count, len(before_list)):
            yield before_list[index], None
        for index in range(pair_count, len(after_list)):
            yield None, after_list[index]
        return

    # --- Strategy 2: unique stable-key fast path ---
    def unique_stable_key_map(elem_list):
        keyed_elements = {}
        for elem in elem_list:
            elem_key = stable_key(elem)
            if elem_key is None or elem_key in keyed_elements:
                return None
            keyed_elements[elem_key] = elem
        return keyed_elements

    before_map = unique_stable_key_map(before_list)
    after_map = unique_stable_key_map(after_list)
    if before_map is not None and after_map is not None and before_list and after_list:
        exact_keys = set(before_map) & set(after_map)
        for key in sorted(exact_keys, key=str):
            yield before_map[key], after_map[key]

        unmatched_before = [
            before_map[key] for key in sorted(set(before_map) - exact_keys, key=str)
        ]
        unmatched_after = [
            after_map[key] for key in sorted(set(after_map) - exact_keys, key=str)
        ]

        overlap_pairs, unmatched_before, unmatched_after = (
            _stable_key_overlap_pairing(
                unmatched_before,
                unmatched_after,
            )
        )
        for before_elem, after_elem in overlap_pairs:
            yield before_elem, after_elem
        for before_elem in unmatched_before:
            yield before_elem, None
        for after_elem in unmatched_after:
            yield None, after_elem
        return

    overlap_pairs, before_list, after_list = _stable_key_overlap_pairing(
        before_list,
        after_list,
    )
    for before_elem, after_elem in overlap_pairs:
        yield before_elem, after_elem

    if overlap_pairs:
        if not before_list:
            for after_elem in after_list:
                yield None, after_elem
            return
        if not after_list:
            for before_elem in before_list:
                yield before_elem, None
            return

    if not before_list or not after_list:
        for before_elem in before_list:
            yield before_elem, None
        for after_elem in after_list:
            yield None, after_elem
        return

    # --- Strategy 3: bucket then discriminate ---
    def primary_bucket_key(elem: etree._Element) -> tuple:
        """
        Coarse grouping key so that elements of the same general type are
        compared against each other before falling back to position.
        """
        table_key = narrative_table_key(elem)
        if table_key:
            return ("narr_table", table_key)
        row_key = narrative_row_key(elem)
        if row_key:
            return ("narr_row", row_key)
        elem_stable_key = stable_key(elem)
        if elem_stable_key is not None:
            if (
                isinstance(elem_stable_key, RootExtensionSetKey)
                and elem_stable_key.source
                == RootExtensionSetSource.DIRECT_TEMPLATE_IDS
            ):
                return ("templateId.identities", elem_stable_key.identities)
            return ("stable", elem_stable_key)
        return ("tag", elem.tag)

    before_buckets: Dict = defaultdict(list)
    after_buckets:  Dict = defaultdict(list)
    for elem in before_list:
        before_buckets[primary_bucket_key(elem)].append(elem)
    for elem in after_list:
        after_buckets[primary_bucket_key(elem)].append(elem)

    for bucket_key in sorted(set(before_buckets) | set(after_buckets), key=str):
        bucket_before = before_buckets.get(bucket_key, [])
        bucket_after  = after_buckets.get(bucket_key, [])

        if not bucket_before:
            for after_elem in bucket_after:
                yield None, after_elem
            continue
        if not bucket_after:
            for before_elem in bucket_before:
                yield before_elem, None
            continue

        if len(bucket_before) == 1 and len(bucket_after) == 1:
            yield bucket_before[0], bucket_after[0]
            continue

        # 3a. Prefer-updates soft pairing within templateId.identities buckets
        if isinstance(bucket_key, tuple) and bucket_key[0] == "templateId.identities":
            soft_pairs, bucket_before, bucket_after = _prefer_updates_pairing(
                bucket_before, bucket_after
            )
            for before_elem, after_elem in soft_pairs:
                yield before_elem, after_elem

            if not bucket_before:
                for after_elem in bucket_after:
                    yield None, after_elem
                continue
            if not bucket_after:
                for before_elem in bucket_before:
                    yield before_elem, None
                continue
            if len(bucket_before) == 1 and len(bucket_after) == 1:
                yield bucket_before[0], bucket_after[0]
                continue

        # 3b. Secondary discriminator matching within the remaining bucket
        before_discriminated: Dict = defaultdict(list)
        after_discriminated:  Dict = defaultdict(list)
        for elem in bucket_before:
            before_discriminated[secondary_discriminator(elem)].append(elem)
        for elem in bucket_after:
            after_discriminated[secondary_discriminator(elem)].append(elem)

        for disc_key in sorted(set(before_discriminated) | set(after_discriminated), key=str):
            before_group = before_discriminated.get(disc_key, [])
            after_group  = after_discriminated.get(disc_key, [])
            pair_count   = min(len(before_group), len(after_group))
            for index in range(pair_count):
                yield before_group[index], after_group[index]
            for index in range(pair_count, len(before_group)):
                yield before_group[index], None
            for index in range(pair_count, len(after_group)):
                yield None, after_group[index]
