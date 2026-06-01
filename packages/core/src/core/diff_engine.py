"""
core/diff_engine.py

Core change collection logic.

Provides one public function:
  - collect_additions_updates_deletes: walks the paired trees to collect
    additions, updates, and deletions for JSON output.

Expected eICR version metadata, such as document instance ID, version number,
replacement lineage, and direct document effectiveTime, is ignored so document
bookkeeping does not appear as clinical/content changes.
"""

from typing import List, Optional, Set, Tuple

from lxml import etree

from core.constants import XSI_NS, AddedEntry, DeletedEntry, UpdatedEntry
from core.matching import build_child_groups, match_children_ignore_order
from core.xml_utils import fingerprint, localname, normalize_text

# ---------------------------------------------------------------------------
# Change collection
# ---------------------------------------------------------------------------

IGNORED_CLINICAL_DOCUMENT_CHILD_LOCAL_NAMES = frozenset({
    "id",
    "effectiveTime",
    "versionNumber",
})
IGNORED_CLINICAL_DOCUMENT_ATTRS = frozenset({
    f"{{{XSI_NS}}}schemaLocation",
})


def _is_direct_child_of_clinical_document(node: etree._Element) -> bool:
    """Return True when node is a direct child of the CDA ClinicalDocument."""
    parent = node.getparent()
    return parent is not None and localname(parent) == "ClinicalDocument"


def _is_ignored_version_metadata(node: etree._Element) -> bool:
    """
    Return True for expected eICR document-version bookkeeping nodes.

    These nodes are useful metadata for the after document, but they should not
    be reported as content changes between sequential eICR versions.
    """
    if not isinstance(node.tag, str):
        return False

    if not _is_direct_child_of_clinical_document(node):
        return False

    node_local_name = localname(node)
    if node_local_name in IGNORED_CLINICAL_DOCUMENT_CHILD_LOCAL_NAMES:
        return True

    return node_local_name == "relatedDocument" and node.get("typeCode") == "RPLC"


def _attributes_for_update(node: etree._Element) -> dict:
    """Return attributes used for update detection after metadata filtering."""
    attributes = dict(node.attrib)
    if localname(node) == "ClinicalDocument":
        for ignored_attr in IGNORED_CLINICAL_DOCUMENT_ATTRS:
            attributes.pop(ignored_attr, None)
    return attributes


def _node_updated(before_node: etree._Element, after_node: etree._Element) -> bool:
    """
    Return True if two nodes differ in tag, filtered attributes, or text content.
    """
    return (
            before_node.tag != after_node.tag
            or _attributes_for_update(before_node) != _attributes_for_update(after_node)
            or normalize_text(before_node.text) != normalize_text(after_node.text)
    )


def _prune_to_outermost(nodes: List[etree._Element]) -> List[etree._Element]:
    """
    Remove any node whose ancestor is also in the list, keeping only the
    outermost (highest-level) changed nodes to avoid redundant entries.
    """
    node_set = set(id(node) for node in nodes)
    result   = []
    for node in nodes:
        ancestor = node.getparent()
        dominated = False
        while ancestor is not None:
            if id(ancestor) in node_set:
                dominated = True
                break
            ancestor = ancestor.getparent()
        if not dominated:
            result.append(node)
    return result


def collect_additions_updates_deletes(
        before_root: etree._Element,
        after_root: etree._Element,
) -> Tuple[List[AddedEntry], List[UpdatedEntry], List[DeletedEntry]]:
    """
    Walk the before/after tree pair and collect:
      - added   : elements present only in the after tree
      - updated : elements present in both trees but with changed content,
                  as (before_node, after_node) pairs
      - deleted : elements present only in the before tree

    Expected eICR version bookkeeping directly under ClinicalDocument is
    ignored: document id, document effectiveTime, versionNumber, and RPLC
    relatedDocument lineage.

    After collection, ancestor pruning ensures that if both a parent and a
    child are marked, only the outermost node is kept.

    Returns (added, updated, deleted).
    """
    added_nodes:   List[AddedEntry]   = []
    updated_nodes: List[UpdatedEntry] = []
    deleted_nodes: List[DeletedEntry] = []

    # Track seen node ids to prevent duplicates across recursion paths
    seen_added:   Set[int] = set()
    seen_updated: Set[int] = set()  # keyed on id(after_node)
    seen_deleted: Set[int] = set()

    def recurse(
            before_node: Optional[etree._Element],
            after_node:  Optional[etree._Element],
    ) -> None:
        if before_node is not None and _is_ignored_version_metadata(before_node):
            return
        if after_node is not None and _is_ignored_version_metadata(after_node):
            return

        if before_node is None and after_node is None:
            return

        if before_node is None and after_node is not None:
            if id(after_node) not in seen_added:
                seen_added.add(id(after_node))
                added_nodes.append(after_node)
            return

        if after_node is None and before_node is not None:
            if id(before_node) not in seen_deleted:
                seen_deleted.add(id(before_node))
                deleted_nodes.append(before_node)
            return

        if _node_updated(before_node, after_node):
            if id(after_node) not in seen_updated:
                seen_updated.add(id(after_node))
                updated_nodes.append((before_node, after_node))

        if fingerprint(before_node) == fingerprint(after_node):
            return

        before_groups = build_child_groups(before_node)
        after_groups  = build_child_groups(after_node)

        for tag in sorted(set(before_groups) | set(after_groups), key=str):
            for before_child, after_child in match_children_ignore_order(
                    before_groups.get(tag, []),
                    after_groups.get(tag, []),
            ):
                recurse(before_child, after_child)

    recurse(before_root, after_root)

    # Additions take precedence over updates for the same after_node
    added_ids  = set(id(node) for node in added_nodes)
    updated_nodes = [
        (before, after) for before, after in updated_nodes
        if id(after) not in added_ids
    ]

    pruned_added:   List[AddedEntry]   = _prune_to_outermost(added_nodes)
    pruned_updated_after               = _prune_to_outermost([after for _, after in updated_nodes])
    pruned_updated_ids                 = set(id(node) for node in pruned_updated_after)
    pruned_updated: List[UpdatedEntry] = [
        (before, after) for before, after in updated_nodes
        if id(after) in pruned_updated_ids
    ]
    pruned_deleted: List[DeletedEntry] = _prune_to_outermost(deleted_nodes)

    return pruned_added, pruned_updated, pruned_deleted
