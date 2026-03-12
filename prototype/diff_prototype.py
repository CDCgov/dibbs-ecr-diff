#!/usr/bin/env python3
"""
cda_eicr_diff_with_markers_after.py

Outputs FOUR files:
  1) orig_changed.xml: pruned XML containing ONLY original values (from file1) that changed
  2) new_changed.xml : pruned XML containing ONLY new values (from file2) at the same locations
  3) after_with_change_markers.xml:
        the AFTER XML (file2) with XML comments inserted to annotate:
          - additions (wrap the added element)
          - updates   (wrap the updated element)
          - deletes   (INSERT A STANDALONE COMMENT at the exact sibling position where the node was removed)
  4) changes.json:
        JSON summary of all added/updated/deleted XML, including:
          - didChange: boolean (true if any change detected, else false)
          - xmlPath: stable, human-readable path (stable keys where possible)
          - xPath:   machine-readable XPath using local-name() + stable predicates
        plus document metadata:
          - setId
          - clinicalDocumentId  (ClinicalDocument/id/@root)
          - versionNumber

Defaults:
 - Prefer-updates matching is ON by default. Disable with --no-prefer-updates.
 - Add --debug-match to print matching/pairing decisions.

Key refinement:
 - Narrative <text> tables/rows:
   * Match <table> by header <th> labels (not full fingerprint)
   * Match <tr> by first cell text (not full fingerprint)
   Then diff within rows/cells; <td>/<th> are paired by column position.

Comment un-nesting fix:
 - When inserting a delete marker anchored BEFORE/AFTER an element that is wrapped, we place the
   delete marker BEFORE the Start wrapper (or AFTER the End wrapper) so it does not fall inside
   the wrapper span.

Requires: lxml (pip install lxml)
"""

import argparse
import json
import sys
from collections import defaultdict
from copy import deepcopy
from typing import Optional, Tuple, List, Set, Any, Dict

try:
    from lxml import etree
except ImportError:
    print("This script requires lxml. Install with: pip install lxml", file=sys.stderr)
    sys.exit(1)

KEY_ATTRS = ("ID", "id", "root", "extension", "code")

# Globals set by CLI
PREFER_UPDATES = True   # default ON
DEBUG_MATCH = False


def debug_log(*args, **kwargs):
    if DEBUG_MATCH:
        print(*args, **kwargs)


def norm_text(t: Optional[str]) -> str:
    if t is None:
        return ""
    return " ".join(t.split())


def localname(el: etree._Element) -> str:
    return etree.QName(el).localname


def fingerprint(elem: etree._Element) -> tuple:
    """Order-insensitive subtree fingerprint."""
    tag = elem.tag
    text = norm_text(elem.text)
    attrs = tuple(sorted(elem.attrib.items()))
    child_fps = []
    for c in elem:
        if isinstance(c.tag, str):
            child_fps.append(fingerprint(c))
    child_fps.sort()
    return (tag, text, attrs, tuple(child_fps))


# ---------- XPath helpers (namespace-agnostic via local-name()) ----------

def _first_xpath_attr(elem: etree._Element, xpath_expr: str):
    vals = elem.xpath(xpath_expr)
    if not vals:
        return None
    return vals[0]


def _collect_xpath_attrs(elem: etree._Element, xpath_expr: str, limit: int = 6):
    vals = elem.xpath(xpath_expr)
    if not vals:
        return []
    return list(vals[:limit])


def _first_xpath_node(elem: etree._Element, xpath_expr: str):
    nodes = elem.xpath(xpath_expr)
    if not nodes:
        return None
    return nodes[0]


def _first_xpath_pair_on_node(node: Optional[etree._Element], attr1: str, attr2: str):
    if node is None:
        return None
    v1 = node.get(attr1)
    v2 = node.get(attr2)
    if v1 and v2:
        return (v1, v2)
    return None


# ---------- CDA/eICR helpers ----------

def _statement_xpath_prefix() -> str:
    return (
        "./*[local-name()='entry']"
        "/*[local-name()='act' or local-name()='observation' or local-name()='encounter' "
        "or local-name()='procedure' or local-name()='substanceAdministration' or local-name()='supply' "
        "or local-name()='organizer']"
    )


def _get_statement_node(elem: etree._Element) -> Optional[etree._Element]:
    return _first_xpath_node(elem, _statement_xpath_prefix())


def _template_root(elem: etree._Element) -> Optional[str]:
    return _first_xpath_attr(elem, "./*[local-name()='templateId']/@root")


# ---------- Narrative table/row identity ----------

def narrative_table_key(elem: etree._Element) -> Optional[tuple]:
    """Stable-ish identity for HTML-like tables inside CDA narrative text."""
    if localname(elem) != "table":
        return None

    ths = elem.xpath("./*[local-name()='thead']/*[local-name()='tr'][1]/*[local-name()='th']")
    if ths:
        labels = [norm_text(th.text) for th in ths]
        labels = [l for l in labels if l]
        if labels:
            return ("table.headers", tuple(labels))

    first = elem.xpath(".//*[local-name()='tr'][1]/*[local-name()='th' or local-name()='td'][1]")
    if first:
        t = norm_text(first[0].text)
        if t:
            return ("table.first_cell", t)

    return None


def narrative_row_key(elem: etree._Element) -> Optional[tuple]:
    if localname(elem) != "tr":
        return None

    first = elem.xpath("./*[local-name()='td' or local-name()='th'][1]")
    if first:
        t = norm_text(first[0].text)
        if t:
            return ("row.first_cell", t)

    cells = elem.xpath("./*[local-name()='td' or local-name()='th']")
    joined = "|".join([norm_text(c.text) for c in cells if norm_text(c.text)])
    if joined:
        return ("row.cells", joined)

    return None


# ---------- Stable keys ----------

def stable_key(elem: etree._Element) -> Optional[tuple]:
    items = []
    for a in KEY_ATTRS:
        if a in elem.attrib:
            items.append((a, elem.attrib[a]))
    if items:
        return ("@attrs", tuple(items))

    tpl_root = _first_xpath_attr(elem, "./*[local-name()='templateId']/@root")
    if tpl_root:
        tpl_ext = _first_xpath_attr(elem, "./*[local-name()='templateId']/@extension") or ""
        return ("templateId", ("root", tpl_root), ("extension", tpl_ext))

    id_root = _first_xpath_attr(elem, "./*[local-name()='id']/@root")
    if id_root:
        id_ext = _first_xpath_attr(elem, "./*[local-name()='id']/@extension")
        if id_ext:
            return ("id", ("root", id_root), ("extension", id_ext))
        return ("id", ("root", id_root))

    section_tpl_roots = _collect_xpath_attrs(
        elem,
        ".//*[local-name()='section']/*[local-name()='templateId']/@root",
        limit=8,
    )
    if section_tpl_roots:
        return ("nested.section.templateId.roots", tuple(sorted(section_tpl_roots)))

    stmt = _get_statement_node(elem)
    if stmt is not None:
        stmt_id_root = _first_xpath_attr(stmt, "./*[local-name()='id']/@root")
        stmt_id_ext = _first_xpath_attr(stmt, "./*[local-name()='id']/@extension")
        if stmt_id_root and stmt_id_ext:
            return ("nested.entry.statement.id", ("root", stmt_id_root), ("extension", stmt_id_ext))

        stmt_tpl_roots = _collect_xpath_attrs(stmt, "./*[local-name()='templateId']/@root", limit=8)
        if stmt_tpl_roots:
            return ("nested.entry.statement.templateId.roots", tuple(sorted(stmt_tpl_roots)))

    any_id_root = _first_xpath_attr(elem, ".//*[local-name()='id']/@root")
    any_id_ext = _first_xpath_attr(elem, ".//*[local-name()='id']/@extension")
    if any_id_root and any_id_ext:
        return ("nested.any.id", ("root", any_id_root), ("extension", any_id_ext))

    return None


# ---------- Discriminators ----------

def clinical_statement_id_pair(elem: etree._Element):
    stmt = _get_statement_node(elem)
    if stmt is not None:
        n = _first_xpath_node(stmt, "./*[local-name()='id']")
        pair = _first_xpath_pair_on_node(n, "root", "extension")
        if pair:
            return pair
    n = _first_xpath_node(elem, "./*[local-name()='id']")
    return _first_xpath_pair_on_node(n, "root", "extension")


def clinical_statement_code_pair(elem: etree._Element):
    stmt = _get_statement_node(elem)
    if stmt is not None:
        n = _first_xpath_node(stmt, "./*[local-name()='code']")
        pair = _first_xpath_pair_on_node(n, "code", "codeSystem")
        if pair:
            return pair
    n = _first_xpath_node(elem, "./*[local-name()='code']")
    return _first_xpath_pair_on_node(n, "code", "codeSystem")


def observation_value_discriminator(elem: etree._Element):
    stmt = _get_statement_node(elem)
    obs = None
    if stmt is not None and stmt.xpath("local-name() = 'observation'"):
        obs = stmt

    def from_node(node: etree._Element):
        v = _first_xpath_node(node, "./*[local-name()='value']")
        if v is None:
            return None
        code = v.get("code")
        cs = v.get("codeSystem")
        if code and cs:
            return ("value.code", (code, cs))
        val = v.get("value")
        if val:
            return ("value.value", val)
        txt = norm_text(v.text)
        if txt:
            return ("value.text", txt)
        return None

    if obs is not None:
        d = from_node(obs)
        if d:
            return ("obs", d)

    d = from_node(elem)
    if d:
        return ("direct", d)

    return None


def effective_time_discriminator_from(node: etree._Element):
    v = _first_xpath_attr(node, "./*[local-name()='effectiveTime']/@value")
    if v:
        return ("effectiveTime.value", v)
    low = _first_xpath_attr(node, "./*[local-name()='effectiveTime']/*[local-name()='low']/@value")
    high = _first_xpath_attr(node, "./*[local-name()='effectiveTime']/*[local-name()='high']/@value")
    if low or high:
        return ("effectiveTime.lowhigh", (low or "", high or ""))
    center = _first_xpath_attr(node, "./*[local-name()='effectiveTime']/*[local-name()='center']/@value")
    if center:
        return ("effectiveTime.center", center)
    period_value = _first_xpath_attr(node, "./*[local-name()='effectiveTime']/*[local-name()='period']/@value")
    period_unit = _first_xpath_attr(node, "./*[local-name()='effectiveTime']/*[local-name()='period']/@unit")
    if period_value or period_unit:
        return ("effectiveTime.period", (period_value or "", period_unit or ""))
    return None


def clinical_statement_effective_time(elem: etree._Element):
    stmt = _get_statement_node(elem)
    if stmt is not None:
        et = effective_time_discriminator_from(stmt)
        if et:
            return et
    return effective_time_discriminator_from(elem)


def secondary_discriminator(elem: etree._Element):
    tk = narrative_table_key(elem)
    if tk:
        return ("narr_table", tk)

    rk = narrative_row_key(elem)
    if rk:
        return ("narr_row", rk)

    id_pair = clinical_statement_id_pair(elem)
    if id_pair:
        return ("id", id_pair)

    code_pair = clinical_statement_code_pair(elem)
    if code_pair:
        return ("code", code_pair)

    if not PREFER_UPDATES:
        ov = observation_value_discriminator(elem)
        if ov:
            return ("obs_value", ov)

    et = clinical_statement_effective_time(elem)
    if et:
        return ("time", et)

    return ("fp", fingerprint(elem))


# ---------- Prefer-updates soft context key ----------

def _nearest_organizer_context_signature(elem: etree._Element) -> tuple:
    cur = elem.getparent()
    while cur is not None:
        if localname(cur) == "organizer":
            idp = clinical_statement_id_pair(cur)
            if idp:
                return ("organizer.id", idp)
            tpl = _template_root(cur) or ""
            cp = clinical_statement_code_pair(cur) or ("", "")
            et = clinical_statement_effective_time(cur) or ("", "")
            return ("organizer.ctx", (tpl, cp, et))
        cur = cur.getparent()
    return ("organizer.none", "")


def soft_context_key(elem: etree._Element) -> Optional[tuple]:
    idp = clinical_statement_id_pair(elem)
    if idp:
        return ("id", idp)

    tpl = _template_root(elem)
    if not tpl:
        return None

    et = clinical_statement_effective_time(elem) or ("", "")
    org = _nearest_organizer_context_signature(elem)
    cp = clinical_statement_code_pair(elem) or ("", "")

    return ("ctx", (tpl, et, org, cp))


# ---------- Child grouping/matching ----------

def build_child_groups(parent: etree._Element) -> dict:
    groups = defaultdict(list)
    for c in parent:
        if isinstance(c.tag, str):
            groups[c.tag].append(c)
    return groups


def _is_table_cell_list(lst: List[etree._Element]) -> bool:
    return bool(lst) and all(localname(e) in ("td", "th") for e in lst)


def _prefer_updates_pairing(L1: List[etree._Element], L2: List[etree._Element]):
    m1 = defaultdict(list)
    m2 = defaultdict(list)
    for e in L1:
        m1[soft_context_key(e)].append(e)
    for e in L2:
        m2[soft_context_key(e)].append(e)

    pairs = []
    u1 = []
    u2 = []

    keys = set(m1.keys()) | set(m2.keys())
    keys.discard(None)

    for k in sorted(keys, key=lambda x: str(x)):
        a = m1.get(k, [])
        b = m2.get(k, [])
        n = min(len(a), len(b))
        for i in range(n):
            pairs.append((a[i], b[i]))
            debug_log(f"[soft-pair] key={k}")
        for i in range(n, len(a)):
            u1.append(a[i])
        for i in range(n, len(b)):
            u2.append(b[i])

    u1.extend(m1.get(None, []))
    u2.extend(m2.get(None, []))
    return pairs, u1, u2


def match_children_ignore_order(list1: List[etree._Element], list2: List[etree._Element]):
    # Table cells: pair by column position
    if _is_table_cell_list(list1) and _is_table_cell_list(list2):
        n = min(len(list1), len(list2))
        for i in range(n):
            yield list1[i], list2[i]
        for i in range(n, len(list1)):
            yield list1[i], None
        for i in range(n, len(list2)):
            yield None, list2[i]
        return

    # Unique stable_key fast path
    def unique_keys(lst):
        ks = []
        for e in lst:
            k = stable_key(e)
            if k is None:
                return None
            ks.append(k)
        if len(set(ks)) != len(ks):
            return None
        return ks

    k1 = unique_keys(list1)
    k2 = unique_keys(list2)
    if k1 is not None and k2 is not None and list1 and list2:
        m1 = {stable_key(e): e for e in list1}
        m2 = {stable_key(e): e for e in list2}
        for k in sorted(set(m1.keys()) | set(m2.keys()), key=lambda x: str(x)):
            yield m1.get(k), m2.get(k)
        return

    # Bucket by primary key
    def primary_bucket_key(e: etree._Element) -> tuple:
        tk = narrative_table_key(e)
        if tk:
            return ("narr_table", tk)
        rk = narrative_row_key(e)
        if rk:
            return ("narr_row", rk)

        tpl_root = _first_xpath_attr(e, "./*[local-name()='templateId']/@root")
        if tpl_root:
            return ("templateId.root", tpl_root)

        sk = stable_key(e)
        if sk is not None:
            return ("stable", sk)

        return ("tag", e.tag)

    b1 = defaultdict(list)
    b2 = defaultdict(list)
    for e in list1:
        b1[primary_bucket_key(e)].append(e)
    for e in list2:
        b2[primary_bucket_key(e)].append(e)

    for pkey in sorted(set(b1.keys()) | set(b2.keys()), key=lambda x: str(x)):
        L1 = b1.get(pkey, [])
        L2 = b2.get(pkey, [])

        if not L1:
            for e2 in L2:
                yield None, e2
            continue
        if not L2:
            for e1 in L1:
                yield e1, None
            continue

        if len(L1) == 1 and len(L2) == 1:
            yield L1[0], L2[0]
            continue

        # Prefer-updates soft pairing for templateId.root buckets
        if PREFER_UPDATES and isinstance(pkey, tuple) and len(pkey) >= 2 and pkey[0] == "templateId.root":
            soft_pairs, rem1, rem2 = _prefer_updates_pairing(L1, L2)
            for a, b in soft_pairs:
                yield a, b
            L1, L2 = rem1, rem2

            if not L1:
                for e2 in L2:
                    yield None, e2
                continue
            if not L2:
                for e1 in L1:
                    yield e1, None
                continue
            if len(L1) == 1 and len(L2) == 1:
                yield L1[0], L2[0]
                continue

        # Secondary discriminator matching
        d1 = defaultdict(list)
        d2 = defaultdict(list)
        for e in L1:
            d1[secondary_discriminator(e)].append(e)
        for e in L2:
            d2[secondary_discriminator(e)].append(e)

        for dkey in sorted(set(d1.keys()) | set(d2.keys()), key=lambda x: str(x)):
            a = d1.get(dkey, [])
            b = d2.get(dkey, [])
            n = min(len(a), len(b))
            for i in range(n):
                yield a[i], b[i]
            for i in range(n, len(a)):
                yield a[i], None
            for i in range(n, len(b)):
                yield None, b[i]


# ---------- Output construction helpers ----------

def make_elem_like(src: etree._Element, nsmap=None) -> etree._Element:
    return etree.Element(src.tag, nsmap=nsmap)


def strip_values(elem: etree._Element):
    elem.text = None
    elem.tail = None
    elem.attrib.clear()


def set_changed_values_only(out_elem: etree._Element, src_elem: etree._Element, changed_text: bool, changed_attrs: Set[str]):
    out_elem.text = src_elem.text if changed_text else None
    out_elem.tail = None
    out_elem.attrib.clear()
    for k in changed_attrs:
        if k in src_elem.attrib:
            out_elem.attrib[k] = src_elem.attrib[k]


# ---------- Diff engine for orig_changed/new_changed ----------

def diff_nodes(e1: Optional[etree._Element], e2: Optional[etree._Element], is_root=False, root_nsmap=None):
    if e1 is None and e2 is None:
        return None, None

    if e1 is None:
        out1 = make_elem_like(e2, nsmap=root_nsmap if is_root else None)
        strip_values(out1)
        out2 = deepcopy(e2)
        return out1, out2

    if e2 is None:
        out2 = make_elem_like(e1, nsmap=root_nsmap if is_root else None)
        strip_values(out2)
        out1 = deepcopy(e1)
        return out1, out2

    if e1.tag != e2.tag:
        return deepcopy(e1), deepcopy(e2)

    if fingerprint(e1) == fingerprint(e2):
        return None, None

    changed_text = (norm_text(e1.text) != norm_text(e2.text))
    changed_attrs = {k for k in set(e1.attrib.keys()) | set(e2.attrib.keys()) if e1.attrib.get(k) != e2.attrib.get(k)}

    g1 = build_child_groups(e1)
    g2 = build_child_groups(e2)

    child_out1 = []
    child_out2 = []

    for tag in sorted(set(g1.keys()) | set(g2.keys()), key=str):
        l1 = g1.get(tag, [])
        l2 = g2.get(tag, [])
        for c1, c2 in match_children_ignore_order(l1, l2):
            o1, o2 = diff_nodes(c1, c2, is_root=False, root_nsmap=None)
            if o1 is not None:
                child_out1.append(o1)
            if o2 is not None:
                child_out2.append(o2)

    any_children_changed = bool(child_out1 or child_out2)
    any_changed_here = changed_text or bool(changed_attrs)

    if not any_changed_here and not any_children_changed:
        return None, None

    nsmap = root_nsmap if is_root else None
    out1 = make_elem_like(e1, nsmap=nsmap)
    out2 = make_elem_like(e1, nsmap=nsmap)

    if any_children_changed:
        strip_values(out1)
        strip_values(out2)
        if any_changed_here:
            set_changed_values_only(out1, e1, changed_text, changed_attrs)
            set_changed_values_only(out2, e2, changed_text, changed_attrs)
    else:
        set_changed_values_only(out1, e1, changed_text, changed_attrs)
        set_changed_values_only(out2, e2, changed_text, changed_attrs)

    for c in child_out1:
        out1.append(c)
    for c in child_out2:
        out2.append(c)

    return out1, out2


# ---------- JSON + marker change collection (captures before/after XML nodes) ----------

ChangeWrap = Tuple[str, etree._Element, Optional[etree._Element]]  # (typ, after_node, before_node_for_updates)
DeleteAnchor = Tuple[etree._Element, Optional[etree._Element], str, etree._Element]  # (parent_after, ref_after, where, deleted_before_node)


def _direct_text_or_attr_changed(n1: etree._Element, n2: etree._Element) -> bool:
    if norm_text(n1.text) != norm_text(n2.text):
        return True
    keys = set(n1.attrib.keys()) | set(n2.attrib.keys())
    for k in keys:
        if n1.attrib.get(k) != n2.attrib.get(k):
            return True
    return False


def collect_changes_and_markers(before_root: etree._Element, after_root: etree._Element):
    added_after: Set[etree._Element] = set()
    updated_pairs: Dict[etree._Element, etree._Element] = {}  # after -> before
    deletes: List[DeleteAnchor] = []

    def mark_updated(b: etree._Element, a: etree._Element):
        updated_pairs[a] = b

    def rec(n1: Optional[etree._Element], n2: Optional[etree._Element]):
        if n1 is None and n2 is None:
            return
        if n1 is None and n2 is not None:
            added_after.add(n2)
            return
        if n1 is not None and n2 is None:
            return

        assert n1 is not None and n2 is not None

        if n1.tag != n2.tag:
            mark_updated(n1, n2)

        if fingerprint(n1) == fingerprint(n2):
            return

        if _direct_text_or_attr_changed(n1, n2):
            mark_updated(n1, n2)

        g1 = build_child_groups(n1)
        g2 = build_child_groups(n2)

        for tag in sorted(set(g1.keys()) | set(g2.keys()), key=str):
            l1 = g1.get(tag, [])
            l2 = g2.get(tag, [])
            pairs = list(match_children_ignore_order(l1, l2))

            for idx, (c1, c2) in enumerate(pairs):
                if c1 is not None and c2 is None:
                    parent_after = n2
                    ref = None
                    where = "end"

                    for j in range(idx + 1, len(pairs)):
                        if pairs[j][1] is not None:
                            ref = pairs[j][1]
                            where = "before"
                            break

                    if ref is None:
                        for j in range(idx - 1, -1, -1):
                            if pairs[j][1] is not None:
                                ref = pairs[j][1]
                                where = "after"
                                break

                    deletes.append((parent_after, ref, where, c1))
                    continue

                rec(c1, c2)

    rec(before_root, after_root)

    # Prefer added over updated
    for a in list(added_after):
        updated_pairs.pop(a, None)

    # prune ancestor wraps among added/updated
    def prune(nodes: Set[etree._Element]) -> Set[etree._Element]:
        pruned = set(nodes)
        for node in list(nodes):
            anc = node.getparent()
            while anc is not None:
                if anc in pruned:
                    pruned.discard(anc)
                anc = anc.getparent()
        return pruned

    added_after = prune(added_after)
    updated_after = prune(set(updated_pairs.keys()))
    updated_pairs = {a: b for a, b in updated_pairs.items() if a in updated_after}

    wraps: List[ChangeWrap] = []
    for a in added_after:
        wraps.append(("added", a, None))
    for a in updated_after:
        wraps.append(("updated", a, updated_pairs.get(a)))

    # de-dupe deletes by anchor + deleted fingerprint
    seen = set()
    deduped_deletes = []
    for parent_after, ref_after, where, deleted_before in deletes:
        key = (id(parent_after), id(ref_after) if ref_after is not None else None, where, fingerprint(deleted_before))
        if key in seen:
            continue
        seen.add(key)
        deduped_deletes.append((parent_after, ref_after, where, deleted_before))

    return wraps, deduped_deletes


# ---------- Map markers onto a fresh AFTER parse (by index path) ----------

def index_path(node: etree._Element) -> Tuple[int, ...]:
    path = []
    cur = node
    while cur is not None and cur.getparent() is not None:
        parent = cur.getparent()
        path.append(parent.index(cur))
        cur = parent
    return tuple(reversed(path))


def node_by_index_path(root: etree._Element, path: Tuple[int, ...]) -> etree._Element:
    cur = root
    for idx in path:
        cur = cur[idx]
    return cur


# Marker tuple for insertion:
# ("wrap", typ, after_node)
# ("delete_at", "deleted", parent_after, ref_after, where)
Marker = tuple


def build_markers_from_changes(wraps: List[ChangeWrap], deletes: List[DeleteAnchor]) -> List[Marker]:
    markers: List[Marker] = []
    for typ, after_node, _before_node in wraps:
        markers.append(("wrap", typ, after_node))
    for parent_after, ref_after, where, _deleted_before in deletes:
        markers.append(("delete_at", "deleted", parent_after, ref_after, where))
    return markers


def map_markers_to_fresh_after(markers: List[Marker], fresh_after_root: etree._Element) -> List[Marker]:
    mapped: List[Marker] = []
    for m in markers:
        if m[0] == "wrap":
            _, typ, el = m
            try:
                mapped_el = node_by_index_path(fresh_after_root, index_path(el))
                mapped.append(("wrap", typ, mapped_el))
            except Exception:
                continue
        else:
            _, typ, parent, ref, where = m
            try:
                mapped_parent = node_by_index_path(fresh_after_root, index_path(parent))
            except Exception:
                continue
            mapped_ref = None
            mapped_where = where
            if ref is not None:
                try:
                    mapped_ref = node_by_index_path(fresh_after_root, index_path(ref))
                except Exception:
                    mapped_ref = None
                    mapped_where = "end"
            mapped.append(("delete_at", typ, mapped_parent, mapped_ref, mapped_where))
    return mapped


# ---------- Placeholder insertion + renumbering (with fixed delete placement) ----------

PH_START = "__CHG_START__"
PH_END = "__CHG_END__"
PH_DEL = "__CHG_DEL__"


def _is_ph_comment(node: Any, kind_prefix: str) -> bool:
    return isinstance(node, etree._Comment) and (node.text or "").startswith(kind_prefix + "|")


def _insert_placeholders(after_root: etree._Element, mapped_markers: List[Marker]) -> None:
    def pos_key(m: Marker) -> Tuple[Any, ...]:
        if m[0] == "wrap":
            _, typ, el = m
            return (index_path(el), 0, 1, {"added": 0, "updated": 1}.get(typ, 9))
        _, _, parent, ref, where = m
        if ref is not None:
            return (index_path(ref), {"before": 0, "after": 2, "end": 3}.get(where, 3), 0, 0)
        return (index_path(parent) + (10**9,), 3, 0, 0)

    ordered = sorted(mapped_markers, key=pos_key)
    placeholders = [(uid + 1, m) for uid, m in enumerate(ordered)]

    for uid, m in reversed(placeholders):
        if m[0] == "wrap":
            _, typ, el = m
            parent = el.getparent()
            c_start = etree.Comment(f"{PH_START}|{uid}|{typ}")
            c_end = etree.Comment(f"{PH_END}|{uid}|{typ}")
            if parent is None:
                el.insert(0, c_start)
                el.append(c_end)
            else:
                idx = parent.index(el)
                parent.insert(idx + 1, c_end)
                parent.insert(idx, c_start)

        else:
            _, _, parent, ref, where = m
            c = etree.Comment(f"{PH_DEL}|{uid}|deleted")

            if ref is None:
                parent.append(c)
                continue

            idx_ref = parent.index(ref)

            if where == "before":
                insert_at = idx_ref
                while insert_at > 0 and _is_ph_comment(parent[insert_at - 1], PH_START):
                    insert_at -= 1
                parent.insert(insert_at, c)

            elif where == "after":
                insert_at = idx_ref + 1
                while insert_at < len(parent) and _is_ph_comment(parent[insert_at], PH_END):
                    insert_at += 1
                parent.insert(insert_at, c)
            else:
                parent.append(c)


def _renumber_placeholders_in_document_order(after_root: etree._Element) -> None:
    uid_order: List[int] = []
    for _, node in etree.iterwalk(after_root, events=("comment",)):
        txt = node.text or ""
        parts = txt.split("|")
        if len(parts) != 3:
            continue
        kind, uid_s, _typ = parts
        if kind not in (PH_START, PH_END, PH_DEL):
            continue
        try:
            uid = int(uid_s)
        except ValueError:
            continue
        if uid not in uid_order:
            uid_order.append(uid)

    x = len(uid_order)
    uid_to_i = {uid: idx + 1 for idx, uid in enumerate(uid_order)}

    for _, node in etree.iterwalk(after_root, events=("comment",)):
        txt = node.text or ""
        parts = txt.split("|")
        if len(parts) != 3:
            continue
        kind, uid_s, typ = parts
        if kind not in (PH_START, PH_END, PH_DEL):
            continue
        try:
            uid = int(uid_s)
        except ValueError:
            continue
        i = uid_to_i.get(uid)
        if i is None:
            continue

        if kind == PH_START:
            node.text = f" Start of change {i} of {x}: {typ} "
        elif kind == PH_END:
            node.text = f" End of change {i} of {x}: {typ} "
        else:
            node.text = f" Change {i} of {x}: deleted "


def apply_markers(after_root: etree._Element, mapped_markers: List[Marker]) -> None:
    _insert_placeholders(after_root, mapped_markers)
    _renumber_placeholders_in_document_order(after_root)


# ---------- Stable human-readable path + machine XPath predicates ----------

def _stable_key_to_str_for_human(sk: Optional[tuple]) -> Optional[str]:
    if sk is None:
        return None
    t0 = sk[0]

    if t0 == "narr_table":
        inner = sk[1]
        if inner and inner[0] == "table.headers":
            return f'headers="{"|".join(inner[1])}"'
        if inner and inner[0] == "table.first_cell":
            return f'first="{inner[1]}"'

    if t0 == "narr_row":
        inner = sk[1]
        if inner and inner[0] == "row.first_cell":
            return f'first="{inner[1]}"'
        if inner and inner[0] == "row.cells":
            return f'cells="{inner[1]}"'

    if t0 == "templateId":
        parts = []
        for part in sk[1:]:
            if isinstance(part, tuple) and len(part) == 2 and part[1]:
                parts.append(f"{part[0]}={part[1]}")
        return "template:" + ";".join(parts) if parts else "template"

    if t0 in ("id", "nested.any.id", "nested.entry.statement.id"):
        parts = []
        for part in sk[1:]:
            if isinstance(part, tuple) and len(part) == 2 and part[1]:
                parts.append(f"{part[0]}={part[1]}")
        return "id:" + ";".join(parts) if parts else "id"

    if t0 == "@attrs":
        attrs = sk[1]
        if attrs:
            pairs = [f"{k}={v}" for k, v in attrs]
            return "attrs:" + ";".join(pairs)

    return None


def stable_xml_path(elem: etree._Element, anchor_root_localname: str = "ClinicalDocument") -> str:
    parts = []
    cur = elem
    while cur is not None:
        if not isinstance(cur.tag, str):
            cur = cur.getparent()
            continue

        ln = localname(cur)

        key = None
        if ln == "table":
            tk = narrative_table_key(cur)
            key = ("narr_table", tk) if tk else None
        elif ln == "tr":
            rk = narrative_row_key(cur)
            key = ("narr_row", rk) if rk else None
        else:
            key = stable_key(cur)

        keystr = _stable_key_to_str_for_human(key)

        parent = cur.getparent()
        if parent is None:
            idx = 1
        else:
            same = [c for c in parent if isinstance(c.tag, str) and localname(c) == ln]
            idx = (same.index(cur) + 1) if cur in same else 1

        if keystr:
            parts.append(f"{ln}[{keystr}]")
        else:
            parts.append(f"{ln}[:{idx}]")

        if ln == anchor_root_localname:
            break
        cur = parent

    return "/" + "/".join(reversed(parts))


def _xpath_escape_literal(s: str) -> str:
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    parts = []
    for chunk in s.split("'"):
        if chunk:
            parts.append(f"'{chunk}'")
        parts.append('"\'"')
    if parts and parts[-1] == '"\'"':
        parts.pop()
    return "concat(" + ",".join(parts) + ")"


def _node_pos_among_same_localname(node: etree._Element) -> int:
    parent = node.getparent()
    if parent is None:
        return 1
    ln = localname(node)
    same = [c for c in parent if isinstance(c.tag, str) and localname(c) == ln]
    try:
        return same.index(node) + 1
    except ValueError:
        return 1


def _effective_time_parts(node: etree._Element) -> Dict[str, str]:
    """Return dict of available effectiveTime parts for node (value, low, high, center, period)."""
    parts = {}
    v = _first_xpath_attr(node, "./*[local-name()='effectiveTime']/@value")
    if v:
        parts["value"] = v
    low = _first_xpath_attr(node, "./*[local-name()='effectiveTime']/*[local-name()='low']/@value")
    high = _first_xpath_attr(node, "./*[local-name()='effectiveTime']/*[local-name()='high']/@value")
    if low or high:
        parts["low"] = low or ""
        parts["high"] = high or ""
    center = _first_xpath_attr(node, "./*[local-name()='effectiveTime']/*[local-name()='center']/@value")
    if center:
        parts["center"] = center
    period_value = _first_xpath_attr(node, "./*[local-name()='effectiveTime']/*[local-name()='period']/@value")
    period_unit = _first_xpath_attr(node, "./*[local-name()='effectiveTime']/*[local-name()='period']/@unit")
    if period_value or period_unit:
        parts["period_value"] = period_value or ""
        parts["period_unit"] = period_unit or ""
    return parts


def xpath_with_predicates(elem: etree._Element, anchor_root_localname: str = "ClinicalDocument") -> str:
    """
    Machine-readable XPath using local-name() steps.
    Adds stable predicates when possible; otherwise uses positional [n].
    Predicates include effectiveTime parts (value/low+high/center/period) to reduce collisions.
    """
    steps = []
    cur = elem

    while cur is not None:
        if not isinstance(cur.tag, str):
            cur = cur.getparent()
            continue

        ln = localname(cur)
        step = f"*[local-name()={_xpath_escape_literal(ln)}]"
        preds: List[str] = []

        if ln == "table":
            tk = narrative_table_key(cur)
            if tk and tk[0] == "table.headers":
                headers = list(tk[1])[:4]
                for i, h in enumerate(headers, start=1):
                    preds.append(
                        f"./*[local-name()='thead']/*[local-name()='tr'][1]/*[local-name()='th'][{i}][normalize-space()={_xpath_escape_literal(h)}]"
                    )
            elif tk and tk[0] == "table.first_cell":
                preds.append(
                    f".//*[local-name()='tr'][1]/*[local-name()='th' or local-name()='td'][1][normalize-space()={_xpath_escape_literal(tk[1])}]"
                )

        elif ln == "tr":
            rk = narrative_row_key(cur)
            if rk and rk[0] == "row.first_cell":
                preds.append(
                    f"./*[local-name()='td' or local-name()='th'][1][normalize-space()={_xpath_escape_literal(rk[1])}]"
                )
            elif rk and rk[0] == "row.cells":
                preds.append(f"contains(normalize-space(string(.)), {_xpath_escape_literal(rk[1][:50])})")

        else:
            id_root = _first_xpath_attr(cur, "./*[local-name()='id']/@root")
            id_ext = _first_xpath_attr(cur, "./*[local-name()='id']/@extension")
            if id_root and id_ext:
                preds.append(
                    f"./*[local-name()='id'][@root={_xpath_escape_literal(id_root)} and @extension={_xpath_escape_literal(id_ext)}]"
                )
            elif id_root:
                preds.append(
                    f"./*[local-name()='id'][@root={_xpath_escape_literal(id_root)}]"
                )

            tpl_root = _first_xpath_attr(cur, "./*[local-name()='templateId']/@root")
            if tpl_root:
                preds.append(
                    f"./*[local-name()='templateId'][@root={_xpath_escape_literal(tpl_root)}]"
                )

            code = _first_xpath_attr(cur, "./*[local-name()='code']/@code")
            cs = _first_xpath_attr(cur, "./*[local-name()='code']/@codeSystem")
            if code and cs:
                preds.append(
                    f"./*[local-name()='code'][@code={_xpath_escape_literal(code)} and @codeSystem={_xpath_escape_literal(cs)}]"
                )

            # effectiveTime predicates
            et_parts = _effective_time_parts(cur)
            if et_parts:
                if "value" in et_parts:
                    preds.append(f"./*[local-name()='effectiveTime'][@value={_xpath_escape_literal(et_parts['value'])}]")
                elif "low" in et_parts or "high" in et_parts:
                    lowv = et_parts.get("low", "")
                    highv = et_parts.get("high", "")
                    conds = []
                    if lowv != "":
                        conds.append(f"./*[local-name()='effectiveTime']/*[local-name()='low'][@value={_xpath_escape_literal(lowv)}]")
                    if highv != "":
                        conds.append(f"./*[local-name()='effectiveTime']/*[local-name()='high'][@value={_xpath_escape_literal(highv)}]")
                    if conds:
                        preds.append(" and ".join(conds))
                elif "center" in et_parts:
                    preds.append(f"./*[local-name()='effectiveTime']/*[local-name()='center'][@value={_xpath_escape_literal(et_parts['center'])}]")
                elif "period_value" in et_parts or "period_unit" in et_parts:
                    pval = et_parts.get("period_value", "")
                    punit = et_parts.get("period_unit", "")
                    conds = []
                    if pval != "":
                        conds.append(f"./*[local-name()='effectiveTime']/*[local-name()='period'][@value={_xpath_escape_literal(pval)}]")
                    if punit != "":
                        conds.append(f"./*[local-name()='effectiveTime']/*[local-name()='period'][@unit={_xpath_escape_literal(punit)}]")
                    if conds:
                        preds.append(" and ".join(conds))

            if cur.get("root"):
                preds.append(f"@root={_xpath_escape_literal(cur.get('root'))}")
            if cur.get("extension"):
                preds.append(f"@extension={_xpath_escape_literal(cur.get('extension'))}")

        if preds:
            step = step + "[" + " and ".join(preds) + "]"
        else:
            step = step + f"[{_node_pos_among_same_localname(cur)}]"

        steps.append(step)

        if ln == anchor_root_localname:
            break
        cur = cur.getparent()

    return "/" + "/".join(reversed(steps))


# ---------- JSON helpers ----------

def get_doc_metadata(root: etree._Element) -> Tuple[str, str, str]:
    setid = root.xpath("string(./*[local-name()='setId']/@root)") or ""
    doc_id_root = root.xpath("string(./*[local-name()='id']/@root)") or ""
    version = root.xpath("string(./*[local-name()='versionNumber']/@value)") or ""
    return setid, doc_id_root, version


def xml_string(elem: etree._Element) -> str:
    return etree.tostring(elem, encoding="unicode", pretty_print=True, with_tail=False)


def write_changes_json(
        out_path: str,
        after_root: etree._Element,
        wraps: List[ChangeWrap],
        deletes: List[DeleteAnchor],
        did_change: bool,
):
    setid, doc_id_root, version = get_doc_metadata(after_root)

    added = []
    updated = []
    deleted = []

    for typ, after_node, before_node in wraps:
        if typ == "added":
            added.append({
                "xmlPath": stable_xml_path(after_node),
                "xPath": xpath_with_predicates(after_node),
                "xml": xml_string(after_node),
            })
        elif typ == "updated":
            updated.append({
                "xmlPath": stable_xml_path(after_node),
                "xPath": xpath_with_predicates(after_node),
                "xmlBefore": xml_string(before_node) if before_node is not None else "",
                "xmlAfter": xml_string(after_node),
            })

    for _parent_after, _ref_after, _where, deleted_before in deletes:
        deleted.append({
            "xmlPath": stable_xml_path(deleted_before),
            "xPath": xpath_with_predicates(deleted_before),
            "xml": xml_string(deleted_before),
        })

    payload = {
        "setId": setid,
        "clinicalDocumentId": doc_id_root,
        "versionNumber": version,
        "didChange": bool(did_change),
        "changes": [
            {"added": added},
            {"updated": updated},
            {"deleted": deleted},
        ],
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


# ---------- Main / CLI ----------

def main():
    global PREFER_UPDATES, DEBUG_MATCH

    ap = argparse.ArgumentParser(
        description="Diff two CDA/eICR XML files and output pruned before/after + AFTER with typed change marker comments + JSON change summary."
    )
    ap.add_argument("file1", help="Original CDA/eICR XML (before)")
    ap.add_argument("file2", help="New CDA/eICR XML (after)")
    ap.add_argument("--out1", default="orig_changed.xml")
    ap.add_argument("--out2", default="new_changed.xml")
    ap.add_argument("--out3", default="after_with_change_markers.xml")
    ap.add_argument("--out5", default="changes.json", help="JSON summary (default: changes.json)")
    ap.add_argument("--no-prefer-updates", action="store_true",
                    help="Disable prefer-updates matching (more conservative identity; may yield add/delete).")
    ap.add_argument("--debug-match", action="store_true",
                    help="Print debug messages about matching/pairing decisions.")
    ap.add_argument("--no-huge", action="store_true")
    args = ap.parse_args()

    PREFER_UPDATES = not args.no_prefer_updates
    DEBUG_MATCH = bool(args.debug_match)

    parser = etree.XMLParser(remove_blank_text=True, huge_tree=not args.no_huge)

    tree_before = etree.parse(args.file1, parser)
    tree_after = etree.parse(args.file2, parser)
    r_before = tree_before.getroot()
    r_after = tree_after.getroot()

    # Determine if *any* changes exist (order-insensitive)
    did_change = (fingerprint(r_before) != fingerprint(r_after))

    root_nsmap = r_before.nsmap

    # Outputs 1 & 2: pruned diffs
    out_r1, out_r2 = diff_nodes(r_before, r_after, is_root=True, root_nsmap=root_nsmap)
    if out_r1 is None:
        out_r1 = etree.Element(r_before.tag, nsmap=root_nsmap)
        strip_values(out_r1)
    if out_r2 is None:
        out_r2 = etree.Element(r_after.tag, nsmap=root_nsmap)
        strip_values(out_r2)

    etree.ElementTree(out_r1).write(args.out1, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    etree.ElementTree(out_r2).write(args.out2, pretty_print=True, xml_declaration=True, encoding="UTF-8")

    # Collect changes for JSON + markers (matched before/after pairs)
    wraps, deletes = collect_changes_and_markers(r_before, r_after)

    # Output 4 (JSON): includes didChange boolean
    write_changes_json(args.out5, r_after, wraps, deletes, did_change=did_change)

    # Output 3: AFTER with markers (fresh parse)
    tree_after_fresh = etree.parse(args.file2, parser)
    r_after_fresh = tree_after_fresh.getroot()

    markers = build_markers_from_changes(wraps, deletes)
    mapped_markers = map_markers_to_fresh_after(markers, r_after_fresh)
    apply_markers(r_after_fresh, mapped_markers)

    etree.ElementTree(r_after_fresh).write(args.out3, pretty_print=True, xml_declaration=True, encoding="UTF-8")

    print(f"Wrote:\n  {args.out1}\n  {args.out2}\n  {args.out3}\n  {args.out5}")
    if PREFER_UPDATES:
        print("Mode: prefer-updates (default). Use --no-prefer-updates to disable.")
    if DEBUG_MATCH:
        print("Debug: --debug-match enabled.")


if __name__ == "__main__":
    main()