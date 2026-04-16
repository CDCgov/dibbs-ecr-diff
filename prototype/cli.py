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
    ap.add_argument(
        "--out5", default="changes.json", help="JSON summary (default: changes.json)"
    )
    ap.add_argument(
        "--no-prefer-updates",
        action="store_true",
        help="Disable prefer-updates matching (more conservative identity; may yield add/delete).",
    )
    ap.add_argument(
        "--debug-match",
        action="store_true",
        help="Print debug messages about matching/pairing decisions.",
    )
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
    did_change = fingerprint(r_before) != fingerprint(r_after)

    root_nsmap = r_before.nsmap

    # Outputs 1 & 2: pruned diffs
    out_r1, out_r2 = diff_nodes(r_before, r_after, is_root=True, root_nsmap=root_nsmap)
    if out_r1 is None:
        out_r1 = etree.Element(r_before.tag, nsmap=root_nsmap)
        strip_values(out_r1)
    if out_r2 is None:
        out_r2 = etree.Element(r_after.tag, nsmap=root_nsmap)
        strip_values(out_r2)

    etree.ElementTree(out_r1).write(
        args.out1, pretty_print=True, xml_declaration=True, encoding="UTF-8"
    )
    etree.ElementTree(out_r2).write(
        args.out2, pretty_print=True, xml_declaration=True, encoding="UTF-8"
    )

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

    etree.ElementTree(r_after_fresh).write(
        args.out3, pretty_print=True, xml_declaration=True, encoding="UTF-8"
    )

    print(f"Wrote:\n  {args.out1}\n  {args.out2}\n  {args.out3}\n  {args.out5}")
    if PREFER_UPDATES:
        print("Mode: prefer-updates (default). Use --no-prefer-updates to disable.")
    if DEBUG_MATCH:
        print("Debug: --debug-match enabled.")


if __name__ == "__main__":
    main()
