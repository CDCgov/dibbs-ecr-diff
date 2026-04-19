from copy import deepcopy

from lxml import etree

from .util import (
    build_child_group,
    empty_copy,
    is_canonically_eq,
    is_table_cell_list,
    normalize_text,
)


def match_children(list_1: list[etree.Element], list_2: list[etree.Element]) -> bool:
    """Matches children nodes for later diffing."""
    if is_table_cell_list(list_1) and is_table_cell_list(list_2):
        # if both list of childrens are table cells
        # order is important to correctly diff for changes/additions/removals
        # 1. first pair overlapping indices
        # 2. then handle extra elements in list 1
        # 3. then handle extra elements in list 2
        n = min(len(list_1), len(list_2))
        for i in range(n):
            yield list_1[i], list_2[i]
        for i in range(n, len(list_1)):
            yield list_1[i], None
        for i in range(n, len(list_2)):
            yield None, list_2[i]
        return


def collect_node_diffs(
    node_1: etree.Element, node_2: etree.Element
) -> tuple[bool, set[str], list[etree.Element], list[etree.Element]]:
    """Collects differing properties between two nodes."""
    has_changed_text = normalize_text(node_1.text) != normalize_text(node_2.text)

    # get all unique keys
    keys = set(node_1.attrib.keys()) | set(node_2.attrib.keys())
    # create set of changed attribute keys
    changed_attrs = {k for k in keys if node_1.attrib.get(k) != node_2.attrib.get(k)}

    group_1 = build_child_group(node_1)
    group_2 = build_child_group(node_2)

    child_out_1: list[etree.Element] = []
    child_out_2: list[etree.Element] = []

    sorted_unique_tags = sorted(set(group_1.keys()) | set(group_2.keys()))
    for tag in sorted_unique_tags:
        list_1 = group_1.get(tag, [])
        list_2 = group_2.get(tag, [])
        for child_1, child_2 in match_children(list_1, list_2):
            out_1, out_2 = diff_nodes(child_1, child_2)
            if out_1 is not None:
                child_out_1.append(out_1)
            if out_2 is not None:
                child_out_2.append(out_2)

    return has_changed_text, changed_attrs, child_out_1, child_out_2


def diff_nodes(
    node_1: etree.Element | None,
    node_2: etree.Element | None,
    is_root: bool = False,
    root_namespace_map: dict[str | None, str] | None = None,
) -> tuple[etree.Element | None, etree.Element | None]:
    """Diff lxml tree nodes."""
    # 1. both nodes are absent, hence, nothing to compare
    if node_1 is None and node_2 is None:
        return None, None

    # 2. either one eICR has nothing to compare to
    # therefore, either a node was added or removed
    # use an empty node to represent the removal/addition
    if node_1 is None and node_2 is not None:
        # create empty node based on node_2
        out_1 = empty_copy(node_2, root_namespace_map)
        out_2 = deepcopy(node_2)
        return out_1, out_2

    if node_2 is None and node_1 is not None:
        # create empty node based on node_1
        out_2 = empty_copy(node_1, root_namespace_map)
        out_1 = deepcopy(node_1)
        return out_1, out_2

    # at this point, we know both nodes are existent
    assert node_1 is not None and node_2 is not None

    # 3. if the tags differ meaning we can't do a partial diff
    # we must do a "full" replace and compare the new structure from top to bottom
    if node_1.tag != node_2.tag:
        return deepcopy(node_1), deepcopy(node_2)

    # 4. both nodes are canonically equal using C14N
    # therefore, nothing to compare
    # see: https://lxml.de/api.html#c14n
    if is_canonically_eq(node_1, node_2):
        return None, None
