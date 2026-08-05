"""CLI entry point for CDA/eICR diff output.

Run with: python -m core file1.xml file2.xml.

Produces a single output: changes.json summarising all additions, updates,
and deletions between the two CDA/eICR documents, after filtering expected
document-version metadata.
"""

import argparse

from lxml import etree

from core.diff_collector import collect_additions_updates_deletes
from core.json_output import write_changes_json


# TODO: should we only create the changes.json file in lower envs and exclude prod?
def main() -> None:
    """Run the CDA/eICR diff CLI."""
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
        "--output",
        default="changes.json",
        help="Output path for JSON change summary (default: changes.json)",
    )
    arg_parser.add_argument(
        "--debug-match",
        action="store_true",
        help="Print verbose output about element matching/pairing decisions",
    )
    args = arg_parser.parse_args()

    xml_parser = etree.XMLParser(remove_blank_text=True, huge_tree=True)

    before_tree = etree.parse(args.file1, xml_parser)
    after_tree = etree.parse(args.file2, xml_parser)
    before_root = before_tree.getroot()
    after_root = after_tree.getroot()

    added, updated, deleted = collect_additions_updates_deletes(before_root, after_root)
    did_change = bool(added or updated or deleted)

    write_changes_json(
        args.output, after_root, added, updated, deleted, did_change=did_change
    )

    if did_change:
        print(f"Wrote:\n  {args.output}")
    else:
        print(f"No meaningful changes detected. Wrote:\n  {args.output}")


if __name__ == "__main__":
    main()
