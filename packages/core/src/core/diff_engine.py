"""
core/diff_engine.py

Core change collection logic.

Provides one public function:
  - collect_additions_updates_deletes: walks the paired trees to collect
    additions, updates, and deletions for JSON output.
"""

from typing import List, Optional, Set, Tuple

from lxml import etree

from core.constants import AddedEntry, UpdatedEntry, DeletedEntry
from core.matching import build_child_groups, match_children_ignore_order
from core.xml_utils import fingerprint, normalize_text


# ---------------------------------------------------------------------------
# Change collection
# ---------------------------------------------------------------------------

def _node_updated(before_node: etree._Element, after_node: etree._Element) -> bool:
    """Return True if the two nodes differ in tag, attributes, or text content."""
    return (
            before_node.tag != after_node.tag
            or before_node.attrib != after_node.attrib
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