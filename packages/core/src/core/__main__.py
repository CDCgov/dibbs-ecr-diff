"""
core/__main__.py

CLI entry point.  Run with:  python -m core file1.xml file2.xml

Produces a single output: changes.json summarising all additions, updates,
and deletions between the two CDA/eICR documents.
"""

import argparse

from lxml import etree

import core.config as _cfg
from core.diff_engine import collect_additions_updates_deletes
from core.json_output import write_changes_json
from core.xml_utils import fingerprint


def main():
    arg_parser = argparse.ArgumentParser(
        description=(
            "Diff two CDA/eICR XML files and produce a JSON summary of all "
            "additions, updates, and deletions."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    arg_parser.add_argument("file1", help="Original CDA/eICR XML (before)")
    arg_parser.add_argument("file2", help="New CDA/eICR XML (after)")
    arg_parser.add_argument(
        "--output", default="changes.json",
        help="Output path for JSON change summary (default: changes.json)",
    )
    arg_parser.add_argument(
        "--debug-match", action="store_true",
        help="Print verbose output about element matching/pairing decisions",
    )
    args = arg_parser.parse_args()

    _cfg.DEBUG_MATCH = bool(args.debug_match)

    xml_parser = etree.XMLParser(remove_blank_text=True, huge_tree=True)

    before_tree = etree.parse(args.file1, xml_parser)
    after_tree  = etree.parse(args.file2, xml_parser)
    before_root = before_tree.getroot()
    after_root  = after_tree.getroot()

    did_change = (fingerprint(before_root) != fingerprint(after_root))

    if not did_change:
        write_changes_json(args.output, after_root, added=[], updated=[], deleted=[], did_change=False)
        print(f"No changes detected. Wrote:\n  {args.output}")
        return

    added, updated, deleted = collect_additions_updates_deletes(before_root, after_root)

    write_changes_json(args.output, after_root, added, updated, deleted, did_change=did_change)

    print(f"Wrote:\n  {args.output}")
    if _cfg.DEBUG_MATCH:
        print("Debug: --debug-match enabled.")


if __name__ == "__main__":
    main()