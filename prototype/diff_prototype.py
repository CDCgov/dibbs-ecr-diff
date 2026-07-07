#!/usr/bin/env python3
"""
cda_eicr_diff_with_markers_after.py

Compares two CDA/eICR XML documents and produces four output files:

  1) orig_changed.xml
        Pruned copy of the BEFORE document containing only elements that changed,
        stripped down to just the changed attributes/text/structure.

  2) new_changed.xml
        Same as above but from the AFTER document — shows what those locations
        look like in the new version.

  3) after_with_change_markers.xml
        The full AFTER document with XML comments injected to annotate every change:
          - additions  → comment pair wrapping the added element
          - updates    → comment pair wrapping the updated element
          - deletions  → standalone comment inserted at the position where the
                         node was removed

  4) changes.json
        Structured summary of all changes, including:
          - didChange          boolean — true if any change was detected
          - xmlPath            stable, human-readable path to the changed element
          - xPath              namespace-aware XPath using the hl7: prefix
          - xml / xmlBefore / xmlAfter   self-contained XML snippets
        Plus document-level metadata: setId, clinicalDocumentId, versionNumber.

Matching behaviour:
  - Prefer-updates mode is ON by default. When multiple elements share the same
    templateId, it tries to pair them as updates rather than add+delete pairs.
    Disable with --no-prefer-updates.
  - Narrative <text> tables and rows are matched by header labels / first-cell
    text rather than full content fingerprint, making narrative diffs more stable.

Namespace handling:
  - All internal XPath queries use the hl7: prefix bound to urn:hl7-org:v3.
  - Generated xPath values in changes.json use the same hl7: prefix.
  - The top-level xPathNamespaceBinding field in changes.json records the binding
    so consumers know how to register it in their XPath engine.
  - XML snippets in changes.json are self-contained: the correct xmlns declarations
    are injected on the snippet root so each snippet is valid standalone XML.

Requires: lxml  (pip install lxml)
"""

import argparse
import json
import sys
from collections import defaultdict
from copy import deepcopy
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from lxml import etree
except ImportError:
    print("This script requires lxml. Install with: pip install lxml", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Attributes treated as stable identity keys when present directly on an element.
#
#   ID, id, root, extension, code  — primary CDA identifiers and coded concept keys
#   moodCode   — distinguishes intent: EVN (occurred) vs RQO (ordered) vs INT (planned)
#   classCode  — distinguishes act class: ACT vs OBS vs ENC etc. on the same tag
#   typeCode   — distinguishes relationship semantics on entryRelationship, participant etc.
#   use        — distinguishes address/telecom purpose: H (home) vs WP (work) vs MC (mobile)
KEY_ATTRS = ("ID", "id", "root", "extension", "code",
             "moodCode", "classCode", "typeCode", "use")

# HL7 namespace used throughout CDA/eICR documents
HL7_NS     = "urn:hl7-org:v3"
HL7_PREFIX = "hl7"

# Passed as namespaces= to every .xpath() call so we can write hl7:tag
# instead of *[local-name()='tag']
NS = {HL7_PREFIX: HL7_NS}

# Placeholder text embedded in XML comments to mark change boundaries before
# they are renumbered into human-readable form
PH_START = "__CHG_START__"
PH_END   = "__CHG_END__"
PH_DEL   = "__CHG_DEL__"

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

# (change_type, after_node, before_node_or_None)
ChangeWrap = Tuple[str, etree._Element, Optional[etree._Element]]

# (parent_in_after, reference_sibling_or_None, placement, deleted_before_node)
DeleteAnchor = Tuple[etree._Element, Optional[etree._Element], str, etree._Element]

# Internal marker tuples passed through the marker pipeline
Marker = tuple

# ---------------------------------------------------------------------------
# Global flags (set by CLI arguments)
# ---------------------------------------------------------------------------

PREFER_UPDATES = True   # --no-prefer-updates disables this
DEBUG_MATCH    = False  # --debug-match enables verbose pairing output


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def debug_log(*args, **kwargs):
    """Print only when --debug-match is active."""
    if DEBUG_MATCH:
        print(*args, **kwargs)


# ---------------------------------------------------------------------------
# Basic XML helpers
# ---------------------------------------------------------------------------

def norm_text(t: Optional[str]) -> str:
    """Collapse internal whitespace and strip leading/trailing whitespace."""
    if t is None:
        return ""
    return " ".join(t.split())


def localname(el: etree._Element) -> str:
    """Return the local part of an element's tag, stripping any namespace URI."""
    return etree.QName(el).localname


def _pfx(tag: str) -> str:
    """Prefixed tag for generated XPath output, e.g. 'id' → 'hl7:id'."""
    return f"{HL7_PREFIX}:{tag}"


def fingerprint(elem: etree._Element) -> tuple:
    """
    Order-insensitive recursive fingerprint for an element subtree.

    Two elements with identical fingerprints are considered unchanged.
    Child fingerprints are sorted before hashing so that sibling reordering
    does not produce a false positive change — intentional for CDA where
    element order within a type group is often not semantically significant.
    """
    tag      = elem.tag
    text     = norm_text(elem.text)
    attrs    = tuple(sorted(elem.attrib.items()))
    children = sorted(fingerprint(c) for c in elem if isinstance(c.tag, str))
    return (tag, text, attrs, tuple(children))


# ---------------------------------------------------------------------------
# XPath query helpers (all use the hl7: namespace prefix)
# ---------------------------------------------------------------------------

def _xpath_attr(elem: etree._Element, expr: str) -> Optional[str]:
    """Return the first string result of an XPath attribute expression, or None."""
    results = elem.xpath(expr, namespaces=NS)
    return results[0] if results else None


def _xpath_attrs(elem: etree._Element, expr: str, limit: int = 6) -> List[str]:
    """Return up to `limit` string results of an XPath attribute expression."""
    return list(elem.xpath(expr, namespaces=NS)[:limit])


def _xpath_node(elem: etree._Element, expr: str) -> Optional[etree._Element]:
    """Return the first element result of an XPath node expression, or None."""
    results = elem.xpath(expr, namespaces=NS)
    return results[0] if results else None


def _attr_pair(node: Optional[etree._Element],
               attr1: str, attr2: str) -> Optional[Tuple[str, str]]:
    """
    Return (attr1_value, attr2_value) from node if both attributes are present,
    otherwise None.
    """
    if node is None:
        return None
    v1, v2 = node.get(attr1), node.get(attr2)
    return (v1, v2) if v1 and v2 else None


# ---------------------------------------------------------------------------
# CDA clinical-statement navigation helpers
# ---------------------------------------------------------------------------

def _clinical_statement_xpath() -> str:
    """
    XPath that selects the primary clinical statement child of an <entry> element.
    Covers all act classes that can appear directly under <entry> in CDA.
    """
    return (
        "./hl7:entry"
        "/*[self::hl7:act or self::hl7:observation or self::hl7:encounter"
        " or self::hl7:procedure or self::hl7:substanceAdministration"
        " or self::hl7:supply or self::hl7:organizer]"
    )


def _get_statement(elem: etree._Element) -> Optional[etree._Element]:
    """
    Return the primary clinical statement node nested under elem (via an <entry>),
    or None if elem does not contain one.
    """
    return _xpath_node(elem, _clinical_statement_xpath())


def _template_root(elem: etree._Element) -> Optional[str]:
    """Return the @root of the first <templateId> child of elem, or None."""
    return _xpath_attr(elem, "./hl7:templateId/@root")


# ---------------------------------------------------------------------------
# Narrative table / row identity
# ---------------------------------------------------------------------------

def narrative_table_key(elem: etree._Element) -> Optional[tuple]:
    """
    Derive a stable identity key for a CDA narrative <table> element.

    Prefers the column header labels from <thead>; falls back to the text of
    the first cell in the first row.  Returns None for non-table elements.
    """
    if localname(elem) != "table":
        return None

    headers = elem.xpath("./hl7:thead/hl7:tr[1]/hl7:th", namespaces=NS)
    if headers:
        labels = [norm_text(th.text) for th in headers if norm_text(th.text)]
        if labels:
            return ("table.headers", tuple(labels))

    first_cell = elem.xpath(
        ".//hl7:tr[1]/*[self::hl7:th or self::hl7:td][1]", namespaces=NS
    )
    if first_cell:
        text = norm_text(first_cell[0].text)
        if text:
            return ("table.first_cell", text)

    return None


def narrative_row_key(elem: etree._Element) -> Optional[tuple]:
    """
    Derive a stable identity key for a CDA narrative <tr> element.

    Prefers the text of the first cell; falls back to all cell text joined
    with a pipe separator.  Returns None for non-tr elements.
    """
    if localname(elem) != "tr":
        return None

    first_cell = elem.xpath("./hl7:td[1] | ./hl7:th[1]", namespaces=NS)
    if first_cell:
        text = norm_text(first_cell[0].text)
        if text:
            return ("row.first_cell", text)

    cells = elem.xpath("./hl7:td | ./hl7:th", namespaces=NS)
    joined = "|".join(norm_text(c.text) for c in cells if norm_text(c.text))
    if joined:
        return ("row.cells", joined)

    return None


# ---------------------------------------------------------------------------
# Stable identity keys (used for element matching across versions)
# ---------------------------------------------------------------------------

def stable_key(elem: etree._Element) -> Optional[tuple]:
    """
    Derive the most specific stable identity key available for elem.

    The key is used to match elements across before/after versions.  Keys are
    tried from most to least specific; the first match wins.

    Priority:
      1. Direct KEY_ATTRS attributes (id, root, extension, code, moodCode, …)
      2. Child <templateId> root + extension
      3. Child <id> root + optional extension
      4. Nested section templateId roots (for component/section wrappers)
      5. Nested entry statement id (root + extension)
      6. Nested entry statement templateId roots
      7. Any descendant id (root + extension)
    """
    items = [(a, elem.attrib[a]) for a in KEY_ATTRS if a in elem.attrib]
    if items:
        return ("@attrs", tuple(items))

    tpl_root = _xpath_attr(elem, "./hl7:templateId/@root")
    if tpl_root:
        tpl_ext = _xpath_attr(elem, "./hl7:templateId/@extension") or ""
        return ("templateId", ("root", tpl_root), ("extension", tpl_ext))

    id_root = _xpath_attr(elem, "./hl7:id/@root")
    if id_root:
        id_ext = _xpath_attr(elem, "./hl7:id/@extension")
        return ("id", ("root", id_root), ("extension", id_ext)) if id_ext \
            else ("id", ("root", id_root))

    section_tpl_roots = _xpath_attrs(
        elem, ".//hl7:section/hl7:templateId/@root", limit=8
    )
    if section_tpl_roots:
        return ("nested.section.templateId.roots", tuple(sorted(section_tpl_roots)))

    stmt = _get_statement(elem)
    if stmt is not None:
        stmt_id_root = _xpath_attr(stmt, "./hl7:id/@root")
        stmt_id_ext  = _xpath_attr(stmt, "./hl7:id/@extension")
        if stmt_id_root and stmt_id_ext:
            return ("nested.entry.statement.id",
                    ("root", stmt_id_root), ("extension", stmt_id_ext))

        stmt_tpl_roots = _xpath_attrs(stmt, "./hl7:templateId/@root", limit=8)
        if stmt_tpl_roots:
            return ("nested.entry.statement.templateId.roots",
                    tuple(sorted(stmt_tpl_roots)))

    any_id_root = _xpath_attr(elem, ".//hl7:id/@root")
    any_id_ext  = _xpath_attr(elem, ".//hl7:id/@extension")
    if any_id_root and any_id_ext:
        return ("nested.any.id", ("root", any_id_root), ("extension", any_id_ext))

    return None


# ---------------------------------------------------------------------------
# Clinical statement discriminators
# ---------------------------------------------------------------------------

def _statement_id_pair(elem: etree._Element) -> Optional[Tuple[str, str]]:
    """Return (root, extension) from the clinical statement's <id>, or None."""
    stmt = _get_statement(elem)
    if stmt is not None:
        pair = _attr_pair(_xpath_node(stmt, "./hl7:id"), "root", "extension")
        if pair:
            return pair
    return _attr_pair(_xpath_node(elem, "./hl7:id"), "root", "extension")


def _statement_code_pair(elem: etree._Element) -> Optional[Tuple[str, str]]:
    """Return (code, codeSystem) from the clinical statement's <code>, or None."""
    stmt = _get_statement(elem)
    if stmt is not None:
        pair = _attr_pair(_xpath_node(stmt, "./hl7:code"), "code", "codeSystem")
        if pair:
            return pair
    return _attr_pair(_xpath_node(elem, "./hl7:code"), "code", "codeSystem")


def _observation_value_discriminator(elem: etree._Element) -> Optional[tuple]:
    """
    Return a discriminator tuple derived from an observation's <value> element.
    Tries coded value, numeric value, then text content — returns None if none found.
    """
    stmt = _get_statement(elem)
    obs  = stmt if (stmt is not None and localname(stmt) == "observation") else None

    def _from_node(node: etree._Element) -> Optional[tuple]:
        v = _xpath_node(node, "./hl7:value")
        if v is None:
            return None
        code, cs = v.get("code"), v.get("codeSystem")
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
        d = _from_node(obs)
        if d:
            return ("obs", d)
    return _from_node(elem)


def _effective_time_discriminator(node: etree._Element) -> Optional[tuple]:
    """
    Return a discriminator tuple from a node's <effectiveTime>, trying each
    representation in order: point value, low/high interval, center, period.
    Returns None if no effectiveTime is found.
    """
    v = _xpath_attr(node, "./hl7:effectiveTime/@value")
    if v:
        return ("effectiveTime.value", v)

    low  = _xpath_attr(node, "./hl7:effectiveTime/hl7:low/@value")
    high = _xpath_attr(node, "./hl7:effectiveTime/hl7:high/@value")
    if low or high:
        return ("effectiveTime.lowhigh", (low or "", high or ""))

    center = _xpath_attr(node, "./hl7:effectiveTime/hl7:center/@value")
    if center:
        return ("effectiveTime.center", center)

    period_value = _xpath_attr(node, "./hl7:effectiveTime/hl7:period/@value")
    period_unit  = _xpath_attr(node, "./hl7:effectiveTime/hl7:period/@unit")
    if period_value or period_unit:
        return ("effectiveTime.period", (period_value or "", period_unit or ""))

    return None


def _statement_effective_time(elem: etree._Element) -> Optional[tuple]:
    """
    Return an effectiveTime discriminator from the nested clinical statement
    if present, otherwise from elem itself.
    """
    stmt = _get_statement(elem)
    if stmt is not None:
        et = _effective_time_discriminator(stmt)
        if et:
            return et
    return _effective_time_discriminator(elem)


def secondary_discriminator(elem: etree._Element) -> tuple:
    """
    Return the best available secondary discriminator for elem.

    Used after primary bucket matching when a bucket contains multiple elements
    that share the same templateId root.  Tried in priority order:
      narrative table key → narrative row key → statement id → statement code
      → (if not prefer-updates) observation value → effectiveTime → fingerprint
    """
    tk = narrative_table_key(elem)
    if tk:
        return ("narr_table", tk)

    rk = narrative_row_key(elem)
    if rk:
        return ("narr_row", rk)

    id_pair = _statement_id_pair(elem)
    if id_pair:
        return ("id", id_pair)

    code_pair = _statement_code_pair(elem)
    if code_pair:
        return ("code", code_pair)

    if not PREFER_UPDATES:
        ov = _observation_value_discriminator(elem)
        if ov:
            return ("obs_value", ov)

    et = _statement_effective_time(elem)
    if et:
        return ("time", et)

    return ("fp", fingerprint(elem))


# ---------------------------------------------------------------------------
# Prefer-updates soft context key
# ---------------------------------------------------------------------------

def _organizer_context(elem: etree._Element) -> tuple:
    """
    Walk up the ancestor chain to find the nearest enclosing <organizer> and
    return a signature tuple for it.  Used so that observations nested inside
    different organizers (lab panels) are not incorrectly paired across panels.
    """
    cur = elem.getparent()
    while cur is not None:
        if localname(cur) == "organizer":
            id_pair = _statement_id_pair(cur)
            if id_pair:
                return ("organizer.id", id_pair)
            tpl = _template_root(cur) or ""
            cp  = _statement_code_pair(cur) or ("", "")
            et  = _statement_effective_time(cur) or ("", "")
            return ("organizer.ctx", (tpl, cp, et))
        cur = cur.getparent()
    return ("organizer.none", "")


def soft_context_key(elem: etree._Element) -> Optional[tuple]:
    """
    Return a soft context key used by prefer-updates pairing.

    When multiple elements share the same templateId, this key tries to pair
    them as updates (same logical entity, changed content) rather than as
    add+delete pairs.  Returns None if no useful context can be derived.
    """
    id_pair = _statement_id_pair(elem)
    if id_pair:
        return ("id", id_pair)

    tpl = _template_root(elem)
    if not tpl:
        return None

    et  = _statement_effective_time(elem) or ("", "")
    org = _organizer_context(elem)
    cp  = _statement_code_pair(elem) or ("", "")
    return ("ctx", (tpl, et, org, cp))


# ---------------------------------------------------------------------------
# Child grouping and matching
# ---------------------------------------------------------------------------

def build_child_groups(parent: etree._Element) -> Dict[str, List[etree._Element]]:
    """
    Group element children of parent by their Clark-notation tag name.
    Comment and PI nodes are excluded.
    """
    groups: Dict[str, List[etree._Element]] = defaultdict(list)
    for child in parent:
        if isinstance(child.tag, str):
            groups[child.tag].append(child)
    return groups


def _is_table_cell_list(lst: List[etree._Element]) -> bool:
    """Return True if every element in lst is a <td> or <th>."""
    return bool(lst) and all(localname(e) in ("td", "th") for e in lst)


def _prefer_updates_pairing(
        L1: List[etree._Element],
        L2: List[etree._Element],
) -> Tuple[List[Tuple], List[etree._Element], List[etree._Element]]:
    """
    Attempt to pair elements from L1 and L2 by their soft context key.

    Returns (matched_pairs, unmatched_from_L1, unmatched_from_L2).
    Elements whose soft context key is None are left unmatched.
    """
    buckets1: Dict = defaultdict(list)
    buckets2: Dict = defaultdict(list)
    for e in L1:
        buckets1[soft_context_key(e)].append(e)
    for e in L2:
        buckets2[soft_context_key(e)].append(e)

    pairs, rem1, rem2 = [], [], []
    all_keys = sorted(
        (set(buckets1) | set(buckets2)) - {None}, key=str
    )

    for k in all_keys:
        a, b = buckets1.get(k, []), buckets2.get(k, [])
        n = min(len(a), len(b))
        for i in range(n):
            pairs.append((a[i], b[i]))
            debug_log(f"[soft-pair] key={k}")
        rem1.extend(a[n:])
        rem2.extend(b[n:])

    rem1.extend(buckets1.get(None, []))
    rem2.extend(buckets2.get(None, []))
    return pairs, rem1, rem2


def match_children_ignore_order(
        list1: List[etree._Element],
        list2: List[etree._Element],
):
    """
    Yield (e1, e2) pairs matching elements from list1 against list2.
    Either side of a pair may be None, indicating an addition (None, e2)
    or deletion (e1, None).

    Matching strategy (applied in order):
      1. Table cells (<td>/<th>) — paired by column position
      2. Unique stable keys on both sides — direct dictionary lookup
      3. Primary bucket by narrative key / templateId root / stable key / tag
         3a. Within templateId.root buckets, try prefer-updates soft pairing
         3b. Within remaining buckets, use secondary discriminator matching
    """
    # --- Strategy 1: column-positional pairing for table cells ---
    if _is_table_cell_list(list1) and _is_table_cell_list(list2):
        n = min(len(list1), len(list2))
        for i in range(n):
            yield list1[i], list2[i]
        for i in range(n, len(list1)):
            yield list1[i], None
        for i in range(n, len(list2)):
            yield None, list2[i]
        return

    # --- Strategy 2: unique stable-key fast path ---
    def all_unique_keys(lst):
        keys = [stable_key(e) for e in lst]
        if None in keys or len(set(keys)) != len(keys):
            return None
        return keys

    k1 = all_unique_keys(list1)
    k2 = all_unique_keys(list2)
    if k1 is not None and k2 is not None and list1 and list2:
        map1 = {stable_key(e): e for e in list1}
        map2 = {stable_key(e): e for e in list2}
        for k in sorted(set(map1) | set(map2), key=str):
            yield map1.get(k), map2.get(k)
        return

    # --- Strategy 3: bucket then discriminate ---
    def primary_bucket_key(e: etree._Element) -> tuple:
        """
        Coarse grouping key so that elements of the same general type are
        compared against each other before falling back to position.
        """
        tk = narrative_table_key(e)
        if tk:
            return ("narr_table", tk)
        rk = narrative_row_key(e)
        if rk:
            return ("narr_row", rk)
        tpl_root = _xpath_attr(e, "./hl7:templateId/@root")
        if tpl_root:
            return ("templateId.root", tpl_root)
        sk = stable_key(e)
        if sk is not None:
            return ("stable", sk)
        return ("tag", e.tag)

    b1: Dict = defaultdict(list)
    b2: Dict = defaultdict(list)
    for e in list1:
        b1[primary_bucket_key(e)].append(e)
    for e in list2:
        b2[primary_bucket_key(e)].append(e)

    for pkey in sorted(set(b1) | set(b2), key=str):
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

        # 3a. Prefer-updates soft pairing within templateId.root buckets
        if (PREFER_UPDATES
                and isinstance(pkey, tuple)
                and pkey[0] == "templateId.root"):
            soft_pairs, L1, L2 = _prefer_updates_pairing(L1, L2)
            for a, b in soft_pairs:
                yield a, b

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

        # 3b. Secondary discriminator matching within the remaining bucket
        d1: Dict = defaultdict(list)
        d2: Dict = defaultdict(list)
        for e in L1:
            d1[secondary_discriminator(e)].append(e)
        for e in L2:
            d2[secondary_discriminator(e)].append(e)

        for dkey in sorted(set(d1) | set(d2), key=str):
            a, b = d1.get(dkey, []), d2.get(dkey, [])
            n = min(len(a), len(b))
            for i in range(n):
                yield a[i], b[i]
            for i in range(n, len(a)):
                yield a[i], None
            for i in range(n, len(b)):
                yield None, b[i]


# ---------------------------------------------------------------------------
# Output element construction helpers
# ---------------------------------------------------------------------------

def make_elem_like(src: etree._Element, nsmap=None) -> etree._Element:
    """Create an empty element with the same tag as src, optionally with nsmap."""
    return etree.Element(src.tag, nsmap=nsmap)


def strip_values(elem: etree._Element):
    """Remove text, tail, and all attributes from elem in-place."""
    elem.text  = None
    elem.tail  = None
    elem.attrib.clear()


def copy_changed_values(
        out_elem: etree._Element,
        src_elem: etree._Element,
        changed_text: bool,
        changed_attrs: Set[str],
):
    """
    Copy only the changed text and attribute values from src_elem into out_elem.
    Unchanged attributes are omitted; tail is always cleared.
    """
    out_elem.text = src_elem.text if changed_text else None
    out_elem.tail = None
    out_elem.attrib.clear()
    for k in changed_attrs:
        if k in src_elem.attrib:
            out_elem.attrib[k] = src_elem.attrib[k]


# ---------------------------------------------------------------------------
# Diff engine — produces orig_changed.xml and new_changed.xml
# ---------------------------------------------------------------------------

def diff_nodes(
        e1: Optional[etree._Element],
        e2: Optional[etree._Element],
        is_root: bool = False,
        root_nsmap=None,
) -> Tuple[Optional[etree._Element], Optional[etree._Element]]:
    """
    Recursively diff two elements and return a (before_out, after_out) pair
    containing only the portions that changed.

    Returns (None, None) when the subtrees are identical.
    When one side is None (addition or deletion), the other side is returned
    in full and the None side is returned as an empty element shell.
    """
    if e1 is None and e2 is None:
        return None, None

    nsmap = root_nsmap if is_root else None

    if e1 is None:
        shell = make_elem_like(e2, nsmap=nsmap)
        strip_values(shell)
        return shell, deepcopy(e2)

    if e2 is None:
        shell = make_elem_like(e1, nsmap=nsmap)
        strip_values(shell)
        return deepcopy(e1), shell

    if e1.tag != e2.tag:
        return deepcopy(e1), deepcopy(e2)

    if fingerprint(e1) == fingerprint(e2):
        return None, None

    changed_text  = (norm_text(e1.text) != norm_text(e2.text))
    changed_attrs = {
        k for k in set(e1.attrib) | set(e2.attrib)
        if e1.attrib.get(k) != e2.attrib.get(k)
    }

    child_out1, child_out2 = [], []
    g1, g2 = build_child_groups(e1), build_child_groups(e2)

    for tag in sorted(set(g1) | set(g2), key=str):
        for c1, c2 in match_children_ignore_order(g1.get(tag, []), g2.get(tag, [])):
            o1, o2 = diff_nodes(c1, c2)
            if o1 is not None:
                child_out1.append(o1)
            if o2 is not None:
                child_out2.append(o2)

    any_children_changed = bool(child_out1 or child_out2)
    any_self_changed     = changed_text or bool(changed_attrs)

    if not any_self_changed and not any_children_changed:
        return None, None

    out1 = make_elem_like(e1, nsmap=nsmap)
    out2 = make_elem_like(e1, nsmap=nsmap)

    if any_children_changed:
        strip_values(out1)
        strip_values(out2)
        if any_self_changed:
            copy_changed_values(out1, e1, changed_text, changed_attrs)
            copy_changed_values(out2, e2, changed_text, changed_attrs)
    else:
        copy_changed_values(out1, e1, changed_text, changed_attrs)
        copy_changed_values(out2, e2, changed_text, changed_attrs)

    for c in child_out1:
        out1.append(c)
    for c in child_out2:
        out2.append(c)

    return out1, out2


# ---------------------------------------------------------------------------
# Change collection — builds the data needed for JSON output and XML markers
# ---------------------------------------------------------------------------

def _self_changed(n1: etree._Element, n2: etree._Element) -> bool:
    """Return True if n1 and n2 differ in text content or any attribute value."""
    if norm_text(n1.text) != norm_text(n2.text):
        return True
    all_keys = set(n1.attrib) | set(n2.attrib)
    return any(n1.attrib.get(k) != n2.attrib.get(k) for k in all_keys)


def collect_changes_and_markers(
        before_root: etree._Element,
        after_root: etree._Element,
) -> Tuple[List[ChangeWrap], List[DeleteAnchor]]:
    """
    Walk the before/after tree pair and collect:
      - added_after   : elements present only in the after tree
      - updated_pairs : elements present in both trees but with changed content,
                        mapping after_node → before_node
      - deletes       : anchor tuples recording where deleted elements were removed

    After collection, ancestor wrapping is pruned so that if both a parent and
    a child are marked, only the outermost node is kept.

    Returns (wraps, deduped_deletes) where wraps is a flat list of
    (type, after_node, before_node_or_None) tuples.
    """
    added_after:   Set[etree._Element]                   = set()
    updated_pairs: Dict[etree._Element, etree._Element]  = {}
    deletes:       List[DeleteAnchor]                    = []

    def rec(n1: Optional[etree._Element], n2: Optional[etree._Element]):
        if n1 is None and n2 is None:
            return

        if n1 is None and n2 is not None:
            added_after.add(n2)
            return

        if n1 is not None and n2 is None:
            return

        if n1.tag != n2.tag or _self_changed(n1, n2):
            updated_pairs[n2] = n1

        if fingerprint(n1) == fingerprint(n2):
            return

        g1 = build_child_groups(n1)
        g2 = build_child_groups(n2)

        for tag in sorted(set(g1) | set(g2), key=str):
            pairs = list(match_children_ignore_order(g1.get(tag, []), g2.get(tag, [])))

            for idx, (c1, c2) in enumerate(pairs):
                if c1 is not None and c2 is None:
                    ref, where = None, "end"
                    for j in range(idx + 1, len(pairs)):
                        if pairs[j][1] is not None:
                            ref, where = pairs[j][1], "before"
                            break
                    if ref is None:
                        for j in range(idx - 1, -1, -1):
                            if pairs[j][1] is not None:
                                ref, where = pairs[j][1], "after"
                                break
                    deletes.append((n2, ref, where, c1))

                elif c1 is None and c2 is not None:
                    added_after.add(c2)

                else:
                    rec(c1, c2)

    rec(before_root, after_root)

    for node in list(added_after):
        updated_pairs.pop(node, None)

    def prune_to_outermost(nodes: Set[etree._Element]) -> Set[etree._Element]:
        """
        Remove any node whose ancestor is also in the set, keeping only the
        outermost (highest-level) changed nodes to avoid redundant wrapping.
        """
        result = set(nodes)
        for node in list(nodes):
            ancestor = node.getparent()
            while ancestor is not None:
                if ancestor in result:
                    result.discard(ancestor)
                ancestor = ancestor.getparent()
        return result

    added_after   = prune_to_outermost(added_after)
    updated_after = prune_to_outermost(set(updated_pairs))
    updated_pairs = {a: b for a, b in updated_pairs.items() if a in updated_after}

    wraps: List[ChangeWrap] = (
            [("added",   a, None)                for a in added_after]
            + [("updated", a, updated_pairs.get(a)) for a in updated_after]
    )

    seen: Set[tuple] = set()
    deduped_deletes: List[DeleteAnchor] = []
    for parent_after, ref_after, where, deleted_before in deletes:
        key = (
            id(parent_after),
            id(ref_after) if ref_after is not None else None,
            where,
            fingerprint(deleted_before),
        )
        if key not in seen:
            seen.add(key)
            deduped_deletes.append((parent_after, ref_after, where, deleted_before))

    return wraps, deduped_deletes


# ---------------------------------------------------------------------------
# Index-path utilities
# ---------------------------------------------------------------------------

def index_path(node: etree._Element) -> Tuple[int, ...]:
    """
    Return the sequence of child indices from the document root down to node.
    Used to relocate a node in a separately parsed tree with identical structure.
    """
    path = []
    cur  = node
    while cur is not None and cur.getparent() is not None:
        parent = cur.getparent()
        path.append(parent.index(cur))
        cur = parent
    return tuple(reversed(path))


def node_by_index_path(root: etree._Element, path: Tuple[int, ...]) -> etree._Element:
    """Walk root's children by the index sequence in path and return the result."""
    cur = root
    for idx in path:
        cur = cur[idx]
    return cur


# ---------------------------------------------------------------------------
# Marker pipeline
# ---------------------------------------------------------------------------

def build_markers(
        wraps: List[ChangeWrap],
        deletes: List[DeleteAnchor],
) -> List[Marker]:
    """Convert collected change records into raw marker tuples."""
    markers: List[Marker] = []
    for typ, after_node, _ in wraps:
        markers.append(("wrap", typ, after_node))
    for parent_after, ref_after, where, _ in deletes:
        markers.append(("delete_at", "deleted", parent_after, ref_after, where))
    return markers


def remap_markers_to_fresh_tree(
        markers: List[Marker],
        fresh_root: etree._Element,
) -> List[Marker]:
    """
    Translate marker node references from the original after-parse into the
    equivalent nodes in a freshly parsed copy of the same document.

    This is necessary because placeholder insertion mutates the tree, which
    would corrupt index-based lookups if we used the original parse.
    Markers that cannot be remapped are silently dropped.
    """
    remapped: List[Marker] = []
    for m in markers:
        if m[0] == "wrap":
            _, typ, el = m
            try:
                remapped.append(("wrap", typ,
                                 node_by_index_path(fresh_root, index_path(el))))
            except Exception:
                continue
        else:
            _, typ, parent, ref, where = m
            try:
                mapped_parent = node_by_index_path(fresh_root, index_path(parent))
            except Exception:
                continue

            mapped_ref, mapped_where = None, where
            if ref is not None:
                try:
                    mapped_ref = node_by_index_path(fresh_root, index_path(ref))
                except Exception:
                    mapped_where = "end"

            remapped.append(("delete_at", typ, mapped_parent, mapped_ref, mapped_where))

    return remapped


def _is_ph_comment(node: Any, kind: str) -> bool:
    """Return True if node is an lxml comment whose text starts with kind|."""
    return (isinstance(node, etree._Comment)
            and (node.text or "").startswith(kind + "|"))


def _insert_placeholder_comments(
        after_root: etree._Element,
        markers: List[Marker],
) -> None:
    """
    Insert placeholder XML comments into after_root for each marker.

    Wrap markers produce a start comment before the element and an end comment
    after it.  Delete markers produce a single comment at the position where the
    deleted node used to be.
    """
    def sort_key(m: Marker) -> tuple:
        if m[0] == "wrap":
            _, typ, el = m
            return (index_path(el), 0, 1, {"added": 0, "updated": 1}.get(typ, 9))
        _, _, parent, ref, where = m
        if ref is not None:
            return (index_path(ref),
                    {"before": 0, "after": 2, "end": 3}.get(where, 3), 0, 0)
        return (index_path(parent) + (10**9,), 3, 0, 0)

    ordered = sorted(markers, key=sort_key)

    for uid, m in reversed(list(enumerate(ordered, start=1))):
        if m[0] == "wrap":
            _, typ, el = m
            parent = el.getparent()
            c_start = etree.Comment(f"{PH_START}|{uid}|{typ}")
            c_end   = etree.Comment(f"{PH_END}|{uid}|{typ}")
            if parent is None:
                el.insert(0, c_start)
                el.append(c_end)
            else:
                idx = parent.index(el)
                parent.insert(idx + 1, c_end)
                parent.insert(idx, c_start)
        else:
            _, _, parent, ref, where = m
            comment = etree.Comment(f"{PH_DEL}|{uid}|deleted")

            if ref is None:
                parent.append(comment)
                continue

            idx_ref = parent.index(ref)
            if where == "before":
                insert_at = idx_ref
                while insert_at > 0 and _is_ph_comment(parent[insert_at - 1], PH_START):
                    insert_at -= 1
                parent.insert(insert_at, comment)
            elif where == "after":
                insert_at = idx_ref + 1
                while (insert_at < len(parent)
                       and _is_ph_comment(parent[insert_at], PH_END)):
                    insert_at += 1
                parent.insert(insert_at, comment)
            else:
                parent.append(comment)


def _renumber_comments_in_document_order(after_root: etree._Element) -> None:
    """
    Replace numeric UIDs in placeholder comments with human-readable ordinals
    in document order.
    """
    uid_order: List[int] = []
    for _, node in etree.iterwalk(after_root, events=("comment",)):
        txt   = node.text or ""
        parts = txt.split("|")
        if len(parts) != 3:
            continue
        kind, uid_s, _ = parts
        if kind not in (PH_START, PH_END, PH_DEL):
            continue
        try:
            uid = int(uid_s)
        except ValueError:
            continue
        if uid not in uid_order:
            uid_order.append(uid)

    total      = len(uid_order)
    uid_to_pos = {uid: pos for pos, uid in enumerate(uid_order, start=1)}

    for _, node in etree.iterwalk(after_root, events=("comment",)):
        txt   = node.text or ""
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
        pos = uid_to_pos.get(uid)
        if pos is None:
            continue

        if kind == PH_START:
            node.text = f" Start of change {pos} of {total}: {typ} "
        elif kind == PH_END:
            node.text = f" End of change {pos} of {total}: {typ} "
        else:
            node.text = f" Change {pos} of {total}: deleted "


def apply_markers(after_root: etree._Element, markers: List[Marker]) -> None:
    """Insert change marker comments into after_root and renumber them."""
    _insert_placeholder_comments(after_root, markers)
    _renumber_comments_in_document_order(after_root)


# ---------------------------------------------------------------------------
# Human-readable xmlPath generation
# ---------------------------------------------------------------------------

def _stable_key_to_label(sk: Optional[tuple]) -> Optional[str]:
    """Convert a stable_key tuple into a concise human-readable bracket label."""
    if sk is None:
        return None
    kind = sk[0]

    if kind == "narr_table":
        inner = sk[1]
        if inner and inner[0] == "table.headers":
            return f'headers="{"|".join(inner[1])}"'
        if inner and inner[0] == "table.first_cell":
            return f'first="{inner[1]}"'

    if kind == "narr_row":
        inner = sk[1]
        if inner and inner[0] == "row.first_cell":
            return f'first="{inner[1]}"'
        if inner and inner[0] == "row.cells":
            return f'cells="{inner[1]}"'

    if kind == "templateId":
        parts = [f"{p[0]}={p[1]}" for p in sk[1:] if isinstance(p, tuple) and p[1]]
        return "template:" + ";".join(parts) if parts else "template"

    if kind in ("id", "nested.any.id", "nested.entry.statement.id"):
        parts = [f"{p[0]}={p[1]}" for p in sk[1:] if isinstance(p, tuple) and p[1]]
        return "id:" + ";".join(parts) if parts else "id"

    if kind == "@attrs":
        return "attrs:" + ";".join(f"{k}={v}" for k, v in sk[1])

    return None


def stable_xml_path(
        elem: etree._Element,
        anchor: str = "ClinicalDocument",
) -> str:
    """
    Return a stable, human-readable path string for elem.

    Uses meaningful bracket labels derived from stable_key / narrative keys
    where available; falls back to positional [:N] notation otherwise.
    Stops ascending at the element whose local name matches `anchor`.
    """
    parts = []
    cur   = elem

    while cur is not None:
        if not isinstance(cur.tag, str):
            cur = cur.getparent()
            continue

        ln = localname(cur)

        if ln == "table":
            tk  = narrative_table_key(cur)
            key = ("narr_table", tk) if tk else None
        elif ln == "tr":
            rk  = narrative_row_key(cur)
            key = ("narr_row", rk) if rk else None
        else:
            key = stable_key(cur)

        label  = _stable_key_to_label(key)
        parent = cur.getparent()

        if parent is None:
            pos = 1
        else:
            siblings = [c for c in parent
                        if isinstance(c.tag, str) and localname(c) == ln]
            pos = (siblings.index(cur) + 1) if cur in siblings else 1

        parts.append(f"{ln}[{label}]" if label else f"{ln}[:{pos}]")

        if ln == anchor:
            break
        cur = parent

    return "/" + "/".join(reversed(parts))


# ---------------------------------------------------------------------------
# Machine-readable xPath generation (hl7: prefix, stable predicates)
# ---------------------------------------------------------------------------

def _xpath_literal(s: str) -> str:
    """
    Wrap s in XPath-safe quotes.  Falls back to concat() when s contains both
    single and double quotes.
    """
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


def _position_among_siblings(node: etree._Element) -> int:
    """Return the 1-based position of node among siblings with the same local name."""
    parent = node.getparent()
    if parent is None:
        return 1
    ln       = localname(node)
    siblings = [c for c in parent if isinstance(c.tag, str) and localname(c) == ln]
    try:
        return siblings.index(node) + 1
    except ValueError:
        return 1


def _effective_time_predicates(node: etree._Element) -> Dict[str, str]:
    """
    Return a dict of available effectiveTime component values for node.
    Keys: "value", "low", "high", "center", "period_value", "period_unit".
    """
    parts: Dict[str, str] = {}

    v = _xpath_attr(node, "./hl7:effectiveTime/@value")
    if v:
        parts["value"] = v
        return parts

    low  = _xpath_attr(node, "./hl7:effectiveTime/hl7:low/@value")
    high = _xpath_attr(node, "./hl7:effectiveTime/hl7:high/@value")
    if low or high:
        parts["low"]  = low  or ""
        parts["high"] = high or ""
        return parts

    center = _xpath_attr(node, "./hl7:effectiveTime/hl7:center/@value")
    if center:
        parts["center"] = center
        return parts

    pval  = _xpath_attr(node, "./hl7:effectiveTime/hl7:period/@value")
    punit = _xpath_attr(node, "./hl7:effectiveTime/hl7:period/@unit")
    if pval or punit:
        parts["period_value"] = pval  or ""
        parts["period_unit"]  = punit or ""

    return parts


def xpath_with_predicates(
        elem: etree._Element,
        anchor: str = "ClinicalDocument",
) -> str:
    """
    Return a machine-readable absolute XPath for elem using hl7: namespace prefix.

    Stable predicates (id, templateId, code, effectiveTime) are used where
    available; positional [N] predicates are used as a fallback.
    Stops ascending at the element whose local name matches `anchor`.
    """
    steps: List[str] = []
    cur   = elem

    while cur is not None:
        if not isinstance(cur.tag, str):
            cur = cur.getparent()
            continue

        ln     = localname(cur)
        qn     = etree.QName(cur.tag)
        tag_step = _pfx(ln) if qn.namespace == HL7_NS else ln
        preds: List[str] = []

        if ln == "table":
            tk = narrative_table_key(cur)
            if tk and tk[0] == "table.headers":
                for i, h in enumerate(list(tk[1])[:4], start=1):
                    preds.append(
                        f"{_pfx('thead')}/{_pfx('tr')}[1]/{_pfx('th')}[{i}]"
                        f"[normalize-space()={_xpath_literal(h)}]"
                    )
            elif tk and tk[0] == "table.first_cell":
                preds.append(
                    f".//{_pfx('tr')}[1]/*[self::{_pfx('th')} or"
                    f" self::{_pfx('td')}][1]"
                    f"[normalize-space()={_xpath_literal(tk[1])}]"
                )

        elif ln == "tr":
            rk = narrative_row_key(cur)
            if rk and rk[0] == "row.first_cell":
                preds.append(
                    f"{_pfx('td')}[1][normalize-space()={_xpath_literal(rk[1])}]"
                    f" or {_pfx('th')}[1][normalize-space()={_xpath_literal(rk[1])}]"
                )
            elif rk and rk[0] == "row.cells":
                preds.append(
                    f"contains(normalize-space(string(.)),"
                    f" {_xpath_literal(rk[1][:50])})"
                )

        else:
            id_root = _xpath_attr(cur, "./hl7:id/@root")
            id_ext  = _xpath_attr(cur, "./hl7:id/@extension")
            if id_root and id_ext:
                preds.append(
                    f"{_pfx('id')}[@root={_xpath_literal(id_root)}"
                    f" and @extension={_xpath_literal(id_ext)}]"
                )
            elif id_root:
                preds.append(f"{_pfx('id')}[@root={_xpath_literal(id_root)}]")

            tpl_root = _xpath_attr(cur, "./hl7:templateId/@root")
            if tpl_root:
                preds.append(
                    f"{_pfx('templateId')}[@root={_xpath_literal(tpl_root)}]"
                )

            code = _xpath_attr(cur, "./hl7:code/@code")
            cs   = _xpath_attr(cur, "./hl7:code/@codeSystem")
            if code and cs:
                preds.append(
                    f"{_pfx('code')}[@code={_xpath_literal(code)}"
                    f" and @codeSystem={_xpath_literal(cs)}]"
                )

            et = _effective_time_predicates(cur)
            if et:
                if "value" in et:
                    preds.append(
                        f"{_pfx('effectiveTime')}[@value={_xpath_literal(et['value'])}]"
                    )
                elif "low" in et or "high" in et:
                    conds = []
                    if et.get("low"):
                        conds.append(
                            f"{_pfx('effectiveTime')}/{_pfx('low')}"
                            f"[@value={_xpath_literal(et['low'])}]"
                        )
                    if et.get("high"):
                        conds.append(
                            f"{_pfx('effectiveTime')}/{_pfx('high')}"
                            f"[@value={_xpath_literal(et['high'])}]"
                        )
                    if conds:
                        preds.append(" and ".join(conds))
                elif "center" in et:
                    preds.append(
                        f"{_pfx('effectiveTime')}/{_pfx('center')}"
                        f"[@value={_xpath_literal(et['center'])}]"
                    )
                elif "period_value" in et or "period_unit" in et:
                    conds = []
                    if et.get("period_value"):
                        conds.append(
                            f"{_pfx('effectiveTime')}/{_pfx('period')}"
                            f"[@value={_xpath_literal(et['period_value'])}]"
                        )
                    if et.get("period_unit"):
                        conds.append(
                            f"{_pfx('effectiveTime')}/{_pfx('period')}"
                            f"[@unit={_xpath_literal(et['period_unit'])}]"
                        )
                    if conds:
                        preds.append(" and ".join(conds))

            if cur.get("root"):
                preds.append(f"@root={_xpath_literal(cur.get('root'))}")
            if cur.get("extension"):
                preds.append(f"@extension={_xpath_literal(cur.get('extension'))}")

        step = tag_step
        step += ("[" + " and ".join(preds) + "]") if preds \
            else f"[{_position_among_siblings(cur)}]"
        steps.append(step)

        if ln == anchor:
            break
        cur = cur.getparent()

    return "/" + "/".join(reversed(steps))


# ---------------------------------------------------------------------------
# Self-contained XML snippet serialization
# ---------------------------------------------------------------------------

def _used_namespaces(elem: etree._Element) -> Set[str]:
    """
    Return the set of namespace URIs actually referenced within elem's subtree —
    either as element namespaces or as attribute namespaces (xsi:type, sdtc:valueSet, …).
    Only referenced namespaces need to appear in the snippet's xmlns declarations.
    """
    used: Set[str] = set()
    for node in elem.iter():
        if not isinstance(node.tag, str):
            continue
        ns = etree.QName(node.tag).namespace
        if ns:
            used.add(ns)
        for attr in node.attrib:
            if attr.startswith("{"):
                used.add(etree.QName(attr).namespace)
    return used


def _snippet_nsmap(elem: etree._Element) -> dict:
    """
    Build a minimal namespace map for a self-contained XML snippet.

    Handles the common CDA pattern of declaring urn:hl7-org:v3 twice —
    once as the default namespace (xmlns=) and once as a named prefix
    (xmlns:cda=).  When both are present, lxml silently drops the default
    namespace when rebuilding an element, leaving snippets namespace-orphaned.

    Fix: always set the element's own namespace as the default (None key) first,
    then add only named prefixes for other namespaces actually used in the subtree,
    skipping any named alias that would duplicate the default namespace URI.
    """
    elem_ns = etree.QName(elem.tag).namespace
    used    = _used_namespaces(elem)

    nsmap: dict = {}
    if elem_ns:
        nsmap[None] = elem_ns

    for prefix, uri in elem.nsmap.items():
        if prefix is None:
            continue
        if uri == elem_ns:
            continue
        if uri in used:
            nsmap[prefix] = uri

    return nsmap


def xml_string(elem: etree._Element) -> str:
    """
    Serialize elem to a self-contained, namespace-correct XML string.

    Elements extracted from within a CDA document inherit their namespace
    declarations from ancestor elements, so a plain etree.tostring() produces
    namespace-orphaned snippets with no xmlns= declaration.

    We fix this by rebuilding the snippet root with a minimal but complete
    namespace map so the output is valid standalone XML.
    """
    if elem.getparent() is None:
        return etree.tostring(elem, encoding="unicode", pretty_print=True,
                              with_tail=False)

    nsmap    = _snippet_nsmap(elem)
    new_root = etree.Element(elem.tag, attrib=elem.attrib, nsmap=nsmap)
    new_root.text = elem.text
    new_root.tail = None
    for child in elem:
        new_root.append(deepcopy(child))

    return etree.tostring(new_root, encoding="unicode", pretty_print=True,
                          with_tail=False)


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def get_doc_metadata(root: etree._Element) -> Tuple[str, str, str]:
    """Extract setId, clinicalDocumentId, and versionNumber from the document root."""
    set_id  = root.xpath("string(hl7:setId/@root)",          namespaces=NS) or ""
    doc_id  = root.xpath("string(hl7:id/@root)",             namespaces=NS) or ""
    version = root.xpath("string(hl7:versionNumber/@value)", namespaces=NS) or ""
    return set_id, doc_id, version


def write_changes_json(
        out_path: str,
        after_root: etree._Element,
        wraps: List[ChangeWrap],
        deletes: List[DeleteAnchor],
        did_change: bool,
) -> None:
    """Write the changes summary to a JSON file at out_path."""
    set_id, doc_id, version = get_doc_metadata(after_root)

    added, updated, deleted = [], [], []

    for typ, after_node, before_node in wraps:
        if typ == "added":
            added.append({
                "xmlPath": stable_xml_path(after_node),
                "xPath":   xpath_with_predicates(after_node),
                "xml":     xml_string(after_node),
            })
        elif typ == "updated":
            updated.append({
                "xmlPath":   stable_xml_path(after_node),
                "xPath":     xpath_with_predicates(after_node),
                "xmlBefore": xml_string(before_node) if before_node is not None else "",
                "xmlAfter":  xml_string(after_node),
            })

    for _, _, _, deleted_before in deletes:
        deleted.append({
            "xmlPath": stable_xml_path(deleted_before),
            "xPath":   xpath_with_predicates(deleted_before),
            "xml":     xml_string(deleted_before),
        })

    payload = {
        "setId":              set_id,
        "clinicalDocumentId": doc_id,
        "versionNumber":      version,
        "didChange":          bool(did_change),
        "xPathNamespaceBinding": {HL7_PREFIX: HL7_NS},
        "changes": [
            {"added":   added},
            {"updated": updated},
            {"deleted": deleted},
        ],
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    global PREFER_UPDATES, DEBUG_MATCH

    ap = argparse.ArgumentParser(
        description=(
            "Diff two CDA/eICR XML files and produce:\n"
            "  1) pruned before/after XMLs showing only changed content\n"
            "  2) the after document annotated with change marker comments\n"
            "  3) a JSON summary of all additions, updates, and deletions"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("file1", help="Original CDA/eICR XML (before)")
    ap.add_argument("file2", help="New CDA/eICR XML (after)")
    ap.add_argument("--out1", default="orig_changed.xml",
                    help="Output path for pruned before-diff (default: orig_changed.xml)")
    ap.add_argument("--out2", default="new_changed.xml",
                    help="Output path for pruned after-diff  (default: new_changed.xml)")
    ap.add_argument("--out3", default="after_with_change_markers.xml",
                    help="Output path for annotated after document")
    ap.add_argument("--out5", default="changes.json",
                    help="Output path for JSON change summary  (default: changes.json)")
    ap.add_argument("--no-prefer-updates", action="store_true",
                    help="Disable prefer-updates matching; may produce more add/delete pairs")
    ap.add_argument("--debug-match", action="store_true",
                    help="Print verbose output about element matching/pairing decisions")
    ap.add_argument("--no-huge", action="store_true",
                    help="Disable lxml huge_tree mode (use for untrusted input)")
    args = ap.parse_args()

    PREFER_UPDATES = not args.no_prefer_updates
    DEBUG_MATCH    = bool(args.debug_match)

    parser = etree.XMLParser(remove_blank_text=True, huge_tree=not args.no_huge)

    tree_before = etree.parse(args.file1, parser)
    tree_after  = etree.parse(args.file2, parser)
    r_before    = tree_before.getroot()
    r_after     = tree_after.getroot()

    did_change = (fingerprint(r_before) != fingerprint(r_after))
    root_nsmap = r_before.nsmap

    if not did_change:
        empty_before = make_elem_like(r_before, nsmap=root_nsmap)
        strip_values(empty_before)
        empty_after = make_elem_like(r_after, nsmap=root_nsmap)
        strip_values(empty_after)

        etree.ElementTree(empty_before).write(
            args.out1, pretty_print=True, xml_declaration=True, encoding="UTF-8")
        etree.ElementTree(empty_after).write(
            args.out2, pretty_print=True, xml_declaration=True, encoding="UTF-8")
        tree_after.write(
            args.out3, pretty_print=True, xml_declaration=True, encoding="UTF-8")
        write_changes_json(args.out5, r_after, wraps=[], deletes=[], did_change=False)

        print(f"No changes detected. Wrote:\n"
              f"  {args.out1}\n  {args.out2}\n  {args.out3}\n  {args.out5}")
        return

    # --- Produce pruned before/after diffs (out1, out2) ---
    out_r1, out_r2 = diff_nodes(r_before, r_after, is_root=True, root_nsmap=root_nsmap)
    if out_r1 is None:
        out_r1 = make_elem_like(r_before, nsmap=root_nsmap)
        strip_values(out_r1)
    if out_r2 is None:
        out_r2 = make_elem_like(r_after, nsmap=root_nsmap)
        strip_values(out_r2)

    etree.ElementTree(out_r1).write(
        args.out1, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    etree.ElementTree(out_r2).write(
        args.out2, pretty_print=True, xml_declaration=True, encoding="UTF-8")

    # --- Collect changes for JSON and markers ---
    wraps, deletes = collect_changes_and_markers(r_before, r_after)

    # --- Write JSON summary (out5) ---
    write_changes_json(args.out5, r_after, wraps, deletes, did_change=did_change)

    # --- Produce annotated after document (out3) ---
    fresh_after      = etree.parse(args.file2, parser).getroot()
    raw_markers      = build_markers(wraps, deletes)
    remapped_markers = remap_markers_to_fresh_tree(raw_markers, fresh_after)
    apply_markers(fresh_after, remapped_markers)

    etree.ElementTree(fresh_after).write(
        args.out3, pretty_print=True, xml_declaration=True, encoding="UTF-8")

    print(f"Wrote:\n  {args.out1}\n  {args.out2}\n  {args.out3}\n  {args.out5}")
    if PREFER_UPDATES:
        print("Mode: prefer-updates (default). Use --no-prefer-updates to disable.")
    if DEBUG_MATCH:
        print("Debug: --debug-match enabled.")


if __name__ == "__main__":
    main()