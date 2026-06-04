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
changed by additions or deletions, wrappers whose direct clinical statement
ID set only changed by additions or deletions, and templateId sets that changed
only by adding or removing conformance declarations.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple, TypeAlias

from lxml import etree

import core.config as _cfg
from core.cda_clinical_statement import CDA_CLINICAL_STATEMENT_TAGS
from core.cda_fallback_keys import secondary_discriminator, soft_context_key
from core.cda_key_models import (
    DirectChildIdElementSetKey,
    DirectChildTemplateIdElementSetKey,
    NestedClinicalStatementIdElementSetKey,
    NestedClinicalStatementTemplateIdElementSetKey,
    NestedSectionIdElementSetKey,
    NestedSectionTemplateIdElementSetKey,
    RootExtension,
    RootExtensionSetKeyBase,
    StableKey,
)
from core.cda_narrative_keys import narrative_row_key, narrative_table_key
from core.cda_stable_key import stable_key
from core.xml_utils import localname

RootExtensionSetKeyTypes: TypeAlias = tuple[type[RootExtensionSetKeyBase], ...]


@dataclass(frozen=True)
class _RootExtensionElementIndex:
    """Elements indexed by root/extensions they can match on."""

    elements_by_root_extension: Dict[RootExtension, List[etree._Element]]
    root_extensions_by_element_id: Dict[int, tuple[RootExtension, ...]]
    elements_by_id: Dict[int, etree._Element]


ID_STABLE_KEY_TYPES: RootExtensionSetKeyTypes = (
    DirectChildIdElementSetKey,
    NestedClinicalStatementIdElementSetKey,
)
SECTION_ID_STABLE_KEY_TYPES: RootExtensionSetKeyTypes = (NestedSectionIdElementSetKey,)
TEMPLATE_ID_STABLE_KEY_TYPES: RootExtensionSetKeyTypes = (
    DirectChildTemplateIdElementSetKey,
    NestedSectionTemplateIdElementSetKey,
    NestedClinicalStatementTemplateIdElementSetKey,
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


def _id_root_extensions_from_stable_key(
        stable_key_value: StableKey | None,
        allowed_key_types: RootExtensionSetKeyTypes,
) -> tuple[RootExtension, ...]:
    """Return <id> root/extensions from allowed stable-key classes."""
    if not isinstance(stable_key_value, allowed_key_types):
        return ()

    return stable_key_value.root_extensions


def _template_id_root_extensions_from_stable_key(
        stable_key_value: StableKey | None,
        allowed_key_types: RootExtensionSetKeyTypes,
) -> tuple[RootExtension, ...]:
    """Return <templateId> root/extensions from allowed stable-key classes."""
    if not isinstance(stable_key_value, allowed_key_types):
        return ()

    return stable_key_value.root_extensions


def _root_extension_sort_key(root_extension: RootExtension) -> tuple[str, str]:
    """Return a deterministic sort key for root/extension match fields."""
    return root_extension.root, root_extension.extension


def _root_extension_set_sort_key(
        root_extensions: set[RootExtension],
) -> tuple[tuple[str, str], ...]:
    """Return a deterministic sort key for a set of root/extensions."""
    return tuple(sorted(
        (
            _root_extension_sort_key(root_extension)
            for root_extension in root_extensions
        ),
    ))


def _build_root_extension_element_index(
        elements: List[etree._Element],
        root_extension_extractor: Callable[
            [etree._Element],
            tuple[RootExtension, ...],
        ],
) -> _RootExtensionElementIndex:
    """Index elements by root/extensions returned from an element extractor."""
    elements_by_root_extension: Dict[
        RootExtension,
        List[etree._Element],
    ] = defaultdict(list)
    root_extensions_by_element_id: Dict[int, tuple[RootExtension, ...]] = {}
    elements_by_id: Dict[int, etree._Element] = {}

    for elem in elements:
        root_extensions = root_extension_extractor(elem)
        if not root_extensions:
            continue

        elem_id = id(elem)
        root_extensions_by_element_id[elem_id] = root_extensions
        elements_by_id[elem_id] = elem

        for root_extension in root_extensions:
            elements_by_root_extension[root_extension].append(elem)

    return _RootExtensionElementIndex(
        elements_by_root_extension=elements_by_root_extension,
        root_extensions_by_element_id=root_extensions_by_element_id,
        elements_by_id=elements_by_id,
    )


def _index_elements_by_stable_key_root_extension(
        elements: List[etree._Element],
        stable_key_root_extension_extractor: Callable[
            [StableKey | None],
            tuple[RootExtension, ...],
        ],
) -> _RootExtensionElementIndex:
    """Index elements by each allowed stable-key root/extension pair."""
    return _build_root_extension_element_index(
        elements,
        lambda elem: stable_key_root_extension_extractor(stable_key(elem)),
    )


def _pair_indexed_elements_by_root_extension(
        before_index: _RootExtensionElementIndex,
        after_index: _RootExtensionElementIndex,
        require_complete_subset: bool = False,
) -> Tuple[List[Tuple], set[int], set[int]]:
    """
    Pair indexed elements that share unambiguous root/extensions.

    A root/extension pair is usable only if it maps to exactly one before
    element and one after element. A candidate pair is accepted only when each
    side has a single possible counterpart. When require_complete_subset is
    true, every root/extension from the smaller set must be shared by the
    larger set.
    """
    candidate_shared_ids: Dict[
        tuple[int, int],
        set[RootExtension],
    ] = defaultdict(set)
    before_candidate_after_ids: Dict[int, set[int]] = defaultdict(set)
    after_candidate_before_ids: Dict[int, set[int]] = defaultdict(set)

    shared_root_extensions = (
        set(before_index.elements_by_root_extension)
        & set(after_index.elements_by_root_extension)
    )
    for root_extension in sorted(shared_root_extensions, key=_root_extension_sort_key):
        before_group = before_index.elements_by_root_extension[root_extension]
        after_group = after_index.elements_by_root_extension[root_extension]
        if len(before_group) != 1 or len(after_group) != 1:
            continue

        before_elem = before_group[0]
        after_elem = after_group[0]
        before_id = id(before_elem)
        after_id = id(after_elem)

        candidate_shared_ids[(before_id, after_id)].add(root_extension)
        before_candidate_after_ids[before_id].add(after_id)
        after_candidate_before_ids[after_id].add(before_id)

    matched_pairs = []
    paired_before_ids = set()
    paired_after_ids = set()

    def _candidate_sort_key(
            candidate: tuple[tuple[int, int], set[RootExtension]],
    ) -> tuple[tuple[str, str], ...]:
        return _root_extension_set_sort_key(candidate[1])

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
            before_root_extensions = set(
                before_index.root_extensions_by_element_id[before_id],
            )
            after_root_extensions = set(
                after_index.root_extensions_by_element_id[after_id],
            )
            shared_root_extensions_for_pair = candidate_shared_ids[pair_key]
            smaller_root_extension_set_size = min(
                len(before_root_extensions),
                len(after_root_extensions),
            )
            if len(shared_root_extensions_for_pair) != smaller_root_extension_set_size:
                continue

        matched_pairs.append((
            before_index.elements_by_id[before_id],
            after_index.elements_by_id[after_id],
        ))
        paired_before_ids.add(before_id)
        paired_after_ids.add(after_id)

    return matched_pairs, paired_before_ids, paired_after_ids


def _unpaired_elements(
        elements: List[etree._Element],
        paired_element_ids: set[int],
) -> List[etree._Element]:
    """Return elements whose object IDs were not paired."""
    return [elem for elem in elements if id(elem) not in paired_element_ids]


def _shared_stable_key_root_extension_pairing(
        before_list: List[etree._Element],
        after_list: List[etree._Element],
        stable_key_root_extension_extractor: Callable[
            [StableKey | None],
            tuple[RootExtension, ...],
        ],
        require_complete_subset: bool = False,
) -> Tuple[List[Tuple], List[etree._Element], List[etree._Element]]:
    """
    Pair elements that share unambiguous stable-key root/extensions.

    When require_complete_subset is true, every root/extension from the smaller
    stable-key set must be shared by the larger set.
    """
    before_index = _index_elements_by_stable_key_root_extension(
        before_list,
        stable_key_root_extension_extractor,
    )
    after_index = _index_elements_by_stable_key_root_extension(
        after_list,
        stable_key_root_extension_extractor,
    )
    matched_pairs, paired_before_ids, paired_after_ids = (
        _pair_indexed_elements_by_root_extension(
            before_index,
            after_index,
            require_complete_subset=require_complete_subset,
        )
    )

    return (
        matched_pairs,
        _unpaired_elements(before_list, paired_before_ids),
        _unpaired_elements(after_list, paired_after_ids),
    )


def _shared_child_id_pairing(
        before_list: List[etree._Element],
        after_list: List[etree._Element],
) -> Tuple[List[Tuple], List[etree._Element], List[etree._Element]]:
    """
    Pair elements that share unambiguous CDA child-id keys.

    This treats repeated CDA <id> values as alternate keys without
    requiring the full child-id sets to match exactly.
    """
    return _shared_stable_key_root_extension_pairing(
        before_list,
        after_list,
        lambda key: _id_root_extensions_from_stable_key(key, ID_STABLE_KEY_TYPES),
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
    return _shared_stable_key_root_extension_pairing(
        before_list,
        after_list,
        lambda key: _id_root_extensions_from_stable_key(
            key,
            SECTION_ID_STABLE_KEY_TYPES,
        ),
        require_complete_subset=True,
    )


def _direct_clinical_statement_child_id_root_extensions(
        element: etree._Element,
) -> tuple[RootExtension, ...]:
    """
    Return child <id> root/extensions from direct clinical statement children.

    This is a weak parent-continuity hint for wrappers with direct clinical
    statement children. It intentionally ignores direct XML ID/id attributes,
    templateId, and code keys to keep this fallback narrow and focused
    on CDA statement instance IDs.
    """
    root_extensions: set[RootExtension] = set()

    for statement_child in element.iterchildren(tag=CDA_CLINICAL_STATEMENT_TAGS):
        statement_key = stable_key(statement_child)
        if isinstance(statement_key, DirectChildIdElementSetKey):
            root_extensions.update(statement_key.root_extensions)

    return tuple(sorted(root_extensions, key=_root_extension_sort_key))


def _index_elements_by_direct_statement_id_root_extension(
        elements: List[etree._Element],
) -> _RootExtensionElementIndex:
    """Index elements by direct clinical statement child <id> root/extensions."""
    return _build_root_extension_element_index(
        elements,
        _direct_clinical_statement_child_id_root_extensions,
    )


def _shared_direct_clinical_statement_id_pairing(
        before_list: List[etree._Element],
        after_list: List[etree._Element],
) -> Tuple[List[Tuple], List[etree._Element], List[etree._Element]]:
    """
    Pair wrappers that share an unambiguous direct statement ID subset.

    This preserves wrapper continuity when direct clinical statements are added
    or deleted, but only when every statement ID root/extension from the
    smaller wrapper is present in the larger wrapper.
    """
    before_index = _index_elements_by_direct_statement_id_root_extension(before_list)
    after_index = _index_elements_by_direct_statement_id_root_extension(after_list)
    matched_pairs, paired_before_ids, paired_after_ids = (
        _pair_indexed_elements_by_root_extension(
            before_index,
            after_index,
            require_complete_subset=True,
        )
    )

    return (
        matched_pairs,
        _unpaired_elements(before_list, paired_before_ids),
        _unpaired_elements(after_list, paired_after_ids),
    )


def _shared_template_id_pairing(
        before_list: List[etree._Element],
        after_list: List[etree._Element],
) -> Tuple[List[Tuple], List[etree._Element], List[etree._Element]]:
    """
    Pair elements that share an unambiguous templateId subset.

    Template IDs identify CDA conformance/type rather than a specific instance,
    so this fallback is weaker than ID-based matching. Each stable-key kind is
    matched separately by key class so direct templateId keys do not pair with
    nested section or nested clinical-statement templateId keys.
    """
    matched_pairs = []

    for key_type in TEMPLATE_ID_STABLE_KEY_TYPES:
        template_id_pairs, before_list, after_list = (
            _shared_stable_key_root_extension_pairing(
                before_list,
                after_list,
                lambda key, key_type=key_type: _template_id_root_extensions_from_stable_key(
                    key,
                    (key_type,),
                ),
                require_complete_subset=True,
            )
        )
        matched_pairs.extend(template_id_pairs)

    return matched_pairs, before_list, after_list


def _stable_key_overlap_pairing(
        before_list: List[etree._Element],
        after_list: List[etree._Element],
) -> Tuple[List[Tuple], List[etree._Element], List[etree._Element]]:
    """
    Apply overlap fallbacks from strongest to weakest stable-key signal.

    Child IDs are more specific than nested section IDs, and both are stronger
    than direct statement ID subsets. TemplateId overlap is tried last because
    it represents conformance/type continuity rather than instance identity.
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

    direct_statement_pairs, before_list, after_list = (
        _shared_direct_clinical_statement_id_pairing(before_list, after_list)
    )
    matched_pairs.extend(direct_statement_pairs)

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
         2c. Unmatched direct clinical-statement containers may pair when one
             direct statement ID set is a complete subset of the other
         2d. Unmatched templateId keys may pair when one templateId set is a
             complete subset of the other
      3. Primary bucket by narrative key / stable key / tag
         Used when stable keys are missing, duplicated, or too broad to finish
         one-to-one pairing by themselves.
         3a. Within templateId.root_extensions buckets, apply prefer-updates soft pairing
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
            if isinstance(elem_stable_key, DirectChildTemplateIdElementSetKey):
                return ("templateId.root_extensions", elem_stable_key.root_extensions)
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

        # 3a. Prefer-updates soft pairing within templateId.root_extensions buckets
        if isinstance(bucket_key, tuple) and bucket_key[0] == "templateId.root_extensions":
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
