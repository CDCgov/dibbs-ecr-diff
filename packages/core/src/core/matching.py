"""Child element matching logic.

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
from collections.abc import Iterator
from dataclasses import dataclass

from lxml import etree

from core.cda.clinical_statement import CDA_CLINICAL_STATEMENT_TAGS
from core.cda.fallback_keys import secondary_discriminator, soft_context_key
from core.cda.key_models import (
    DirectChildTemplateIdElementSetKey,
    RootExtension,
    RootExtensionSetKeyBase,
    StableKey,
)
from core.cda.narrative_keys import narrative_row_key, narrative_table_key
from core.cda.root_extensions import direct_child_root_extensions_for_tag
from core.cda.stable_key import (
    STABLE_KEY_RANKS as RANKS,
)
from core.cda.stable_key import (
    StableKeyCandidates,
    StableKeyRank,
    highest_ranked_stable_key,
    stable_key_candidates,
)
from core.cda.tags import ID_TAG
from core.xml_utils import localname


@dataclass(frozen=True)
class _RootExtensionElementIndex:
    """Elements indexed by root/extensions they can match on."""

    elements_by_root_extension: dict[RootExtension, list[etree._Element]]
    root_extensions_by_element: dict[etree._Element, tuple[RootExtension, ...]]


# ---------------------------------------------------------------------------
# Child grouping
# ---------------------------------------------------------------------------


def build_immediate_child_groups(
    parent: etree._Element,
) -> dict[str, list[etree._Element]]:
    """Group the immediate element children of `parent` by tag name.

    Namespaced tags use Clark notation (`{namespace}localname`);
    unnamespaced tags are plain names.
    """
    groups: dict[str, list[etree._Element]] = defaultdict(list)
    for child in parent.iterchildren(tag=etree.Element):
        if not isinstance(child.tag, str):
            continue
        groups[child.tag].append(child)
    return groups


# ---------------------------------------------------------------------------
# Prefer-updates soft pairing
# ---------------------------------------------------------------------------


def _is_table_cell_list(elements: list[etree._Element]) -> bool:
    """Return True if every element in the list is a <td> or <th>."""
    return bool(elements) and all(localname(elem) in ("td", "th") for elem in elements)


def _prefer_updates_pairing(
    before_elements: list[etree._Element],
    after_elements: list[etree._Element],
) -> tuple[
    list[tuple[etree._Element, etree._Element]],
    list[etree._Element],
    list[etree._Element],
]:
    """Attempt to pair elements by their soft context key.

    Prefer to classify matching elements as updates rather
    than add+delete pairs.

    Returns (matched_pairs, unmatched_from_before, unmatched_from_after).
    Elements whose soft context key is None are left unmatched.
    """
    before_buckets: dict = defaultdict(list)
    after_buckets: dict = defaultdict(list)
    for elem in before_elements:
        before_buckets[soft_context_key(elem)].append(elem)
    for elem in after_elements:
        after_buckets[soft_context_key(elem)].append(elem)

    matched_pairs = []
    unmatched_before = []
    unmatched_after = []

    all_keys = sorted((set(before_buckets) | set(after_buckets)) - {None}, key=str)

    for key in all_keys:
        before_group = before_buckets.get(key, [])
        after_group = after_buckets.get(key, [])
        pair_count = min(len(before_group), len(after_group))
        for index in range(pair_count):
            matched_pairs.append((before_group[index], after_group[index]))
        unmatched_before.extend(before_group[pair_count:])
        unmatched_after.extend(after_group[pair_count:])

    unmatched_before.extend(before_buckets.get(None, []))
    unmatched_after.extend(after_buckets.get(None, []))
    return matched_pairs, unmatched_before, unmatched_after


def _root_extension_sort_key(root_extension: RootExtension) -> tuple[str, str]:
    """Return a deterministic sort key for root/extension match fields."""
    return root_extension.root, root_extension.extension


def _root_extension_set_sort_key(
    root_extensions: set[RootExtension],
) -> tuple[tuple[str, str], ...]:
    """Return a deterministic sort key for a set of root/extensions."""
    return tuple(
        sorted(
            (
                _root_extension_sort_key(root_extension)
                for root_extension in root_extensions
            ),
        )
    )


def _build_root_extension_element_index(
    elements: list[etree._Element],
    root_extensions_by_filtered_elements: dict[
        etree._Element,
        tuple[RootExtension, ...],
    ],
) -> _RootExtensionElementIndex:
    """Index elements by precomputed root/extensions."""
    elements_by_root_extension: dict[
        RootExtension,
        list[etree._Element],
    ] = defaultdict(list)
    root_extensions_by_element: dict[
        etree._Element,
        tuple[RootExtension, ...],
    ] = {}

    for elem in elements:
        root_extensions = root_extensions_by_filtered_elements.get(elem, ())
        if not root_extensions:
            continue

        root_extensions_by_element[elem] = root_extensions

        for root_extension in root_extensions:
            elements_by_root_extension[root_extension].append(elem)

    return _RootExtensionElementIndex(
        elements_by_root_extension=elements_by_root_extension,
        root_extensions_by_element=root_extensions_by_element,
    )


def _match_elements_by_root_extension(
    before_elements: list[etree._Element],
    after_elements: list[etree._Element],
    root_extensions_by_filtered_elements: dict[
        etree._Element,
        tuple[RootExtension, ...],
    ],
    require_complete_subset: bool,
) -> tuple[
    list[tuple[etree._Element, etree._Element]],
    list[etree._Element],
    list[etree._Element],
]:
    """Match elements using shared root/extension values.

    Elements are first matched if a root-extension value appears on one element
    in the before elements and one element in the after elements. This rejects both
    one-to-many and many-to-one matches.

    When ``require_complete_subset`` is true, every root/extension from the
    element with the smaller root/extension set must be contained in the larger
    root/extension set from the other element.
    """
    before_root_extension_element_index = _build_root_extension_element_index(
        before_elements,
        root_extensions_by_filtered_elements,
    )
    after_root_extension_element_index = _build_root_extension_element_index(
        after_elements,
        root_extensions_by_filtered_elements,
    )
    shared_root_extensions_by_element_pair: dict[
        tuple[etree._Element, etree._Element],
        set[RootExtension],
    ] = defaultdict(set)
    candidate_after_elements_by_before_element: dict[
        etree._Element,
        set[etree._Element],
    ] = defaultdict(set)
    candidate_before_elements_by_after_element: dict[
        etree._Element,
        set[etree._Element],
    ] = defaultdict(set)

    shared_root_extensions = set(
        before_root_extension_element_index.elements_by_root_extension
    ) & set(after_root_extension_element_index.elements_by_root_extension)
    for root_extension in sorted(shared_root_extensions, key=_root_extension_sort_key):
        before_group = before_root_extension_element_index.elements_by_root_extension[
            root_extension
        ]
        after_group = after_root_extension_element_index.elements_by_root_extension[
            root_extension
        ]
        if len(before_group) != 1 or len(after_group) != 1:
            continue

        before_elem = before_group[0]
        after_elem = after_group[0]

        shared_root_extensions_by_element_pair[(before_elem, after_elem)].add(
            root_extension
        )
        candidate_after_elements_by_before_element[before_elem].add(after_elem)
        candidate_before_elements_by_after_element[after_elem].add(before_elem)

    matches = []
    matched_before_elements: set[etree._Element] = set()
    matched_after_elements: set[etree._Element] = set()

    for before_after_pair, _ in sorted(
        shared_root_extensions_by_element_pair.items(),
        key=lambda candidate: _root_extension_set_sort_key(candidate[1]),
    ):
        before_elem, after_elem = before_after_pair

        if len(candidate_after_elements_by_before_element[before_elem]) != 1:
            continue
        if len(candidate_before_elements_by_after_element[after_elem]) != 1:
            continue
        if require_complete_subset:
            before_root_extensions = set(
                before_root_extension_element_index.root_extensions_by_element[
                    before_elem
                ],
            )
            after_root_extensions = set(
                after_root_extension_element_index.root_extensions_by_element[
                    after_elem
                ],
            )
            shared_root_extensions_for_match = shared_root_extensions_by_element_pair[
                before_after_pair
            ]
            smaller_root_extension_set_size = min(
                len(before_root_extensions),
                len(after_root_extensions),
            )
            if len(shared_root_extensions_for_match) != smaller_root_extension_set_size:
                continue

        matches.append(
            (
                before_elem,
                after_elem,
            )
        )
        matched_before_elements.add(before_elem)
        matched_after_elements.add(after_elem)

    return (
        matches,
        [elem for elem in before_elements if elem not in matched_before_elements],
        [elem for elem in after_elements if elem not in matched_after_elements],
    )


def _root_extension_subset_matching_for_stable_key(
    unmatched_before_elements: list[etree._Element],
    unmatched_after_elements: list[etree._Element],
    stable_key_candidates_by_element: dict[etree._Element, StableKeyCandidates],
    stable_key_rank: StableKeyRank,
    require_complete_subset: bool,
) -> tuple[
    list[tuple[etree._Element, etree._Element]],
    list[etree._Element],
    list[etree._Element],
]:
    """Match elements using root/extensions for one stable-key candidate type.

    When ``require_complete_subset`` is true, every root/extension from the element with
    the smaller root/extension set must be shared by the element with the
    larger root/extension set. Otherwise, one shared root/extension is sufficient.
    """
    root_extensions_for_key_by_element: dict[
        etree._Element,
        tuple[RootExtension, ...],
    ] = {}
    for elem in unmatched_before_elements + unmatched_after_elements:
        candidate = stable_key_candidates_by_element[elem][stable_key_rank]
        if isinstance(candidate, RootExtensionSetKeyBase):
            root_extensions_for_key_by_element[elem] = candidate.root_extensions

    return _match_elements_by_root_extension(
        unmatched_before_elements,
        unmatched_after_elements,
        root_extensions_for_key_by_element,
        require_complete_subset=require_complete_subset,
    )


def _child_id_partial_subset_matching(
    unmatched_before_elements: list[etree._Element],
    unmatched_after_elements: list[etree._Element],
    stable_key_candidates_by_element: dict[etree._Element, StableKeyCandidates],
) -> tuple[
    list[tuple[etree._Element, etree._Element]],
    list[etree._Element],
    list[etree._Element],
]:
    """Match elements that share at least one child-ID root/extension."""
    child_id_partial_subset_matches = []
    for stable_key_rank in (
        RANKS.DIRECT_CHILD_ID_RANK,
        RANKS.CLINICAL_STATEMENT_ID_RANK,
    ):
        id_matches, unmatched_before_elements, unmatched_after_elements = (
            _root_extension_subset_matching_for_stable_key(
                unmatched_before_elements,
                unmatched_after_elements,
                stable_key_candidates_by_element,
                stable_key_rank,
                require_complete_subset=False,
            )
        )
        child_id_partial_subset_matches.extend(id_matches)

    return (
        child_id_partial_subset_matches,
        unmatched_before_elements,
        unmatched_after_elements,
    )


def _nested_section_id_complete_subset_matching(
    unmatched_before_elements: list[etree._Element],
    unmatched_after_elements: list[etree._Element],
    stable_key_candidates_by_element: dict[etree._Element, StableKeyCandidates],
) -> tuple[
    list[tuple[etree._Element, etree._Element]],
    list[etree._Element],
    list[etree._Element],
]:
    """Match wrappers that share an unambiguous nested-section ID subset.

    This preserves wrapper continuity when sections are added or deleted, but
    only if all section IDs from the smaller wrapper are present in the larger
    wrapper.
    """
    return _root_extension_subset_matching_for_stable_key(
        unmatched_before_elements,
        unmatched_after_elements,
        stable_key_candidates_by_element,
        RANKS.SECTION_ID_RANK,
        require_complete_subset=True,
    )


def _direct_clinical_statement_child_id_root_extensions(
    element: etree._Element,
) -> tuple[RootExtension, ...]:
    """Return child <id> root/extensions from direct clinical statement children.

    This is a weak parent-continuity hint for wrappers with direct clinical
    statement children. It intentionally ignores direct XML ID/id attributes,
    templateId, and code keys to keep this fallback narrow and focused
    on CDA statement instance IDs.
    """
    root_extensions: set[RootExtension] = set()

    for statement_child in element.iterchildren(tag=CDA_CLINICAL_STATEMENT_TAGS):
        root_extensions.update(
            direct_child_root_extensions_for_tag(
                statement_child,
                ID_TAG,
            )
        )

    return tuple(sorted(root_extensions, key=_root_extension_sort_key))


def _direct_clinical_statement_id_complete_subset_matching(
    unmatched_before_elements: list[etree._Element],
    unmatched_after_elements: list[etree._Element],
    _stable_key_candidates_by_element: dict[
        etree._Element,
        StableKeyCandidates,
    ],
) -> tuple[
    list[tuple[etree._Element, etree._Element]],
    list[etree._Element],
    list[etree._Element],
]:
    """Match wrappers that share an unambiguous direct statement ID subset.

    This preserves wrapper continuity when direct clinical statements are added
    or deleted, but only when every statement ID root/extension from the
    smaller wrapper is present in the larger wrapper. The stable-key candidate
    cache is intentionally unused.
    """
    direct_statement_root_extensions_by_element = {
        elem: _direct_clinical_statement_child_id_root_extensions(elem)
        for elem in unmatched_before_elements + unmatched_after_elements
    }

    return _match_elements_by_root_extension(
        unmatched_before_elements,
        unmatched_after_elements,
        direct_statement_root_extensions_by_element,
        require_complete_subset=True,
    )


def _template_id_complete_subset_matching(
    unmatched_before_elements: list[etree._Element],
    unmatched_after_elements: list[etree._Element],
    stable_key_candidates_by_element: dict[etree._Element, StableKeyCandidates],
) -> tuple[
    list[tuple[etree._Element, etree._Element]],
    list[etree._Element],
    list[etree._Element],
]:
    """Match elements that share an unambiguous templateId subset.

    Template IDs identify CDA conformance/type rather than a specific instance,
    so this fallback is weaker than ID-based matching. Each stable-key kind is
    matched separately by key class so direct templateId keys do not match with
    nested section or nested clinical-statement templateId keys.
    """
    matches = []

    for stable_key_rank in (
        RANKS.DIRECT_CHILD_TEMPLATE_ID_RANK,
        RANKS.SECTION_TEMPLATE_ID_RANK,
        RANKS.CLINICAL_STATEMENT_TEMPLATE_ID_RANK,
    ):
        template_id_matches, unmatched_before_elements, unmatched_after_elements = (
            _root_extension_subset_matching_for_stable_key(
                unmatched_before_elements,
                unmatched_after_elements,
                stable_key_candidates_by_element,
                stable_key_rank,
                require_complete_subset=True,
            )
        )
        matches.extend(template_id_matches)

    return matches, unmatched_before_elements, unmatched_after_elements


def _stable_key_subset_matching(
    unmatched_before_sibling_elements: list[etree._Element],
    unmatched_after_sibling_elements: list[etree._Element],
    stable_key_candidates_by_element: dict[etree._Element, StableKeyCandidates],
) -> tuple[
    list[tuple[etree._Element, etree._Element]],
    list[etree._Element],
    list[etree._Element],
]:
    """Apply subset fallbacks in descending order of key strength.

    Child IDs are more specific than nested section IDs, and both are stronger
    than direct statement ID subsets. TemplateId subset matching is tried last because
    template IDs represent conformance/type continuity rather than instance identity.
    Sets of code candidates are intentionally excluded: codes describe
    classification and are used only for exact ranked matching, not as fallback
    instance-identity evidence.

    A partial subset match can match elements when their key sets share at least one
    value::

        before: {id-a, id-b}
        after:  {id-a, id-c}

    A full subset match can match elements when every key in the smaller set is
    present in the larger set::

        before: {id-a, id-b}
        after:  {id-a, id-b, id-c}

    Elements must have a 1 to 1 match for any subset matching method. One-to-many and
    many-to-one matches are not accepted.
    """
    ranked_subset_matching_methods = (
        _child_id_partial_subset_matching,
        _nested_section_id_complete_subset_matching,
        _direct_clinical_statement_id_complete_subset_matching,
        _template_id_complete_subset_matching,
    )
    subset_matches: list[tuple[etree._Element, etree._Element]] = []

    for subset_matching_method in ranked_subset_matching_methods:
        matches, unmatched_before_sibling_elements, unmatched_after_sibling_elements = (
            subset_matching_method(
                unmatched_before_sibling_elements,
                unmatched_after_sibling_elements,
                stable_key_candidates_by_element,
            )
        )
        subset_matches.extend(matches)

        if (
            not unmatched_before_sibling_elements
            or not unmatched_after_sibling_elements
        ):
            break

    return (
        subset_matches,
        unmatched_before_sibling_elements,
        unmatched_after_sibling_elements,
    )


# ---------------------------------------------------------------------------
# Main matching entry point
# ---------------------------------------------------------------------------


def _unique_sibling_elements_by_key(
    sibling_elements: list[etree._Element],
    stable_key_candidates_by_element: dict[
        etree._Element,
        StableKeyCandidates,
    ],
    stable_key_rank: StableKeyRank,
) -> dict[StableKey, etree._Element | None]:
    """Only return elements that don't have a matching sibling for that key type."""
    unique_elements_by_candidate_key: dict[StableKey, etree._Element | None] = {}

    for elem in sibling_elements:
        stable_key_candidate = stable_key_candidates_by_element[elem][stable_key_rank]
        if stable_key_candidate is None:
            continue

        if stable_key_candidate not in unique_elements_by_candidate_key:
            unique_elements_by_candidate_key[stable_key_candidate] = elem
        elif unique_elements_by_candidate_key[stable_key_candidate] is not None:
            # If a sibling element has the same value for its stable key candidate,
            # then it violates the one-to-one matching requirement, so that key
            # cannot be used to match across eICRs
            unique_elements_by_candidate_key[stable_key_candidate] = None

    return unique_elements_by_candidate_key


def _stable_key_matching(
    unmatched_before_sibling_elements: list[etree._Element],
    unmatched_after_sibling_elements: list[etree._Element],
    stable_key_candidates_by_element: dict[
        etree._Element,
        StableKeyCandidates,
    ],
) -> tuple[
    list[tuple[etree._Element, etree._Element]],
    list[etree._Element],
    list[etree._Element],
]:
    """Match elements through ranked, strict one-to-one stable-key passes.

    For each stable-key rank, from strongest to weakest, it:

      1. Builds a before-side index of unique values for that stable-key rank.
      2. Builds an after-side index of unique values for that stable-key rank.
      3. Matches only values that occur exactly once on both sides.
      4. Removes those matched elements from the remaining sibling lists.
      5. Continues with the next rank.
      6. Stops when either side is exhausted.

    This implements a deterministic, multi-pass matching algorithm.

    Returns the matches found and the remaining unmatched before and after
    siblings.
    """
    matched_elements: list[tuple[etree._Element, etree._Element]] = []

    for stable_key_rank in RANKS:
        unique_before_sibling_elements_by_key = _unique_sibling_elements_by_key(
            unmatched_before_sibling_elements,
            stable_key_candidates_by_element,
            stable_key_rank,
        )
        unique_after_sibling_elements_by_key = _unique_sibling_elements_by_key(
            unmatched_after_sibling_elements,
            stable_key_candidates_by_element,
            stable_key_rank,
        )

        matches_found: list[tuple[etree._Element, etree._Element]] = []
        for (
            candidate_key_value,
            before_elem,
        ) in unique_before_sibling_elements_by_key.items():
            after_elem = unique_after_sibling_elements_by_key.get(candidate_key_value)
            if before_elem is not None and after_elem is not None:
                matches_found.append((before_elem, after_elem))

        if not matches_found:
            continue

        matched_elements.extend(matches_found)
        before_elements_matched = {before_elem for before_elem, _ in matches_found}
        after_elements_matched = {after_elem for _, after_elem in matches_found}
        unmatched_before_sibling_elements = [
            elem
            for elem in unmatched_before_sibling_elements
            if elem not in before_elements_matched
        ]
        unmatched_after_sibling_elements = [
            elem
            for elem in unmatched_after_sibling_elements
            if elem not in after_elements_matched
        ]

        if (
            not unmatched_before_sibling_elements
            or not unmatched_after_sibling_elements
        ):
            break

    return (
        matched_elements,
        unmatched_before_sibling_elements,
        unmatched_after_sibling_elements,
    )


def match_children_ignore_order(
    unmatched_before_sibling_elements: list[etree._Element],
    unmatched_after_sibling_elements: list[etree._Element],
) -> Iterator[tuple[etree._Element | None, etree._Element | None]]:
    """Yield pairs matching elements from the before list against the after list.

    Either side of a pair may be None, indicating an
    addition (None, after_elem) or deletion (before_elem, None).

    Matching strategy (applied in order):
      1. Table cells (<td>/<th>) — paired by column position
      2. Ranked stable-key matching — progressively match strict one-to-one
         stable-key candidates, removing matched siblings after each rank
      3. Stable-key subset fallbacks:
         3a. Child-ID candidates — match on at least one shared ID
         3b. Nested-section ID candidates — match when one ID set is a
             complete subset of the other
         3c. Wrapper elements containing direct clinical statements — match
             when one direct statement ID set is a complete subset of the other
         3d. Template-ID candidates — match when one template-ID set is a
             complete subset of the other
      4. Bucket and discriminate — group remaining siblings by narrative key,
         stable key, or tag, then apply soft-context and secondary matching
         Used when stable keys are missing, duplicated, or too broad to finish
         one-to-one pairing by themselves.
         4a. Within templateId.root_extensions buckets, apply prefer-updates
             soft pairing
         4b. Within remaining buckets, use secondary discriminator matching
    """
    # --- Strategy 1: column-positional pairing for table cells ---
    if _is_table_cell_list(unmatched_before_sibling_elements) and _is_table_cell_list(
        unmatched_after_sibling_elements
    ):
        pair_count = min(
            len(unmatched_before_sibling_elements),
            len(unmatched_after_sibling_elements),
        )
        for index in range(pair_count):
            yield (
                unmatched_before_sibling_elements[index],
                unmatched_after_sibling_elements[index],
            )
        for index in range(pair_count, len(unmatched_before_sibling_elements)):
            yield unmatched_before_sibling_elements[index], None
        for index in range(pair_count, len(unmatched_after_sibling_elements)):
            yield None, unmatched_after_sibling_elements[index]
        return

    # --- Strategy 2: ranked strict one-to-one stable-key passes ---
    stable_key_candidates_by_element = {
        elem: stable_key_candidates(elem)
        for elem in unmatched_before_sibling_elements + unmatched_after_sibling_elements
    }
    (
        stable_key_matches,
        unmatched_before_sibling_elements,
        unmatched_after_sibling_elements,
    ) = _stable_key_matching(
        unmatched_before_sibling_elements,
        unmatched_after_sibling_elements,
        stable_key_candidates_by_element,
    )
    for before_elem, after_elem in stable_key_matches:
        yield before_elem, after_elem

    (
        stable_key_subset_matches,
        unmatched_before_sibling_elements,
        unmatched_after_sibling_elements,
    ) = _stable_key_subset_matching(
        unmatched_before_sibling_elements,
        unmatched_after_sibling_elements,
        stable_key_candidates_by_element,
    )
    for before_elem, after_elem in stable_key_subset_matches:
        yield before_elem, after_elem

    if not unmatched_before_sibling_elements or not unmatched_after_sibling_elements:
        for before_elem in unmatched_before_sibling_elements:
            yield before_elem, None
        for after_elem in unmatched_after_sibling_elements:
            yield None, after_elem
        return

    # --- Strategy 3: bucket then discriminate ---
    def primary_bucket_key(elem: etree._Element) -> tuple:
        """Creates coarse grouping key.

        Used so that elements of the same general type are compared
        against each other before falling back to position.
        """
        table_key = narrative_table_key(elem)
        if table_key:
            return ("narr_table", table_key)
        row_key = narrative_row_key(elem)
        if row_key:
            return ("narr_row", row_key)
        elem_stable_key = highest_ranked_stable_key(elem)
        if elem_stable_key is not None:
            if isinstance(elem_stable_key, DirectChildTemplateIdElementSetKey):
                return ("templateId.root_extensions", elem_stable_key.root_extensions)
            return ("stable", elem_stable_key)
        return ("tag", elem.tag)

    before_buckets: dict = defaultdict(list)
    after_buckets: dict = defaultdict(list)
    for elem in unmatched_before_sibling_elements:
        before_buckets[primary_bucket_key(elem)].append(elem)
    for elem in unmatched_after_sibling_elements:
        after_buckets[primary_bucket_key(elem)].append(elem)

    for bucket_key in sorted(set(before_buckets) | set(after_buckets), key=str):
        bucket_before = before_buckets.get(bucket_key, [])
        bucket_after = after_buckets.get(bucket_key, [])

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
        if (
            isinstance(bucket_key, tuple)
            and bucket_key[0] == "templateId.root_extensions"
        ):
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
        before_discriminated: dict = defaultdict(list)
        after_discriminated: dict = defaultdict(list)
        for elem in bucket_before:
            before_discriminated[secondary_discriminator(elem)].append(elem)
        for elem in bucket_after:
            after_discriminated[secondary_discriminator(elem)].append(elem)

        for disc_key in sorted(
            set(before_discriminated) | set(after_discriminated), key=str
        ):
            before_group = before_discriminated.get(disc_key, [])
            after_group = after_discriminated.get(disc_key, [])
            pair_count = min(len(before_group), len(after_group))
            for index in range(pair_count):
                yield before_group[index], after_group[index]
            for index in range(pair_count, len(before_group)):
                yield before_group[index], None
            for index in range(pair_count, len(after_group)):
                yield None, after_group[index]
