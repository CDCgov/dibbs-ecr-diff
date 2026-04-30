"""
core/matching.py

Child element matching machinery.

Responsible for pairing elements from a before-tree sibling list against
elements from the corresponding after-tree sibling list, yielding (e1, e2)
pairs where either side may be None to indicate an addition or deletion.

Prefer-updates pairing is always active: when multiple elements share the
same templateId, the soft context key is used to preferentially pair them
as updates rather than add+delete pairs.
"""

from collections import defaultdict
from typing import Dict, List, Tuple

from lxml import etree

import core.config as _cfg
from core.cda_identity import (
    narrative_table_key, narrative_row_key,
    secondary_discriminator, soft_context_key, stable_key,
)
from core.xml_utils import _xpath_attr, localname


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
            _cfg.debug_log(f"[soft-pair] key={key}")
        unmatched_before.extend(before_group[pair_count:])
        unmatched_after.extend(after_group[pair_count:])

    unmatched_before.extend(before_buckets.get(None, []))
    unmatched_after.extend(after_buckets.get(None, []))
    return matched_pairs, unmatched_before, unmatched_after


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
      3. Primary bucket by narrative key / templateId root / stable key / tag
         3a. Within templateId.root buckets, apply prefer-updates soft pairing
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
    def all_unique_keys(elem_list):
        keys = [stable_key(elem) for elem in elem_list]
        if None in keys or len(set(keys)) != len(keys):
            return None
        return keys

    before_keys = all_unique_keys(before_list)
    after_keys  = all_unique_keys(after_list)
    if before_keys is not None and after_keys is not None and before_list and after_list:
        before_map = {stable_key(elem): elem for elem in before_list}
        after_map  = {stable_key(elem): elem for elem in after_list}
        for key in sorted(set(before_map) | set(after_map), key=str):
            yield before_map.get(key), after_map.get(key)
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
        template_root = _xpath_attr(elem, "./hl7:templateId/@root")
        if template_root:
            return ("templateId.root", template_root)
        elem_stable_key = stable_key(elem)
        if elem_stable_key is not None:
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

        # 3a. Prefer-updates soft pairing within templateId.root buckets
        if isinstance(bucket_key, tuple) and bucket_key[0] == "templateId.root":
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