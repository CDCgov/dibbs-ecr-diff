import argparse

from core import diff_xml
from core.models import DiffingOptions


def main() -> None:
    """CLI entrypoint."""
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
    opts = DiffingOptions(**vars(args))

    xml = diff_xml(opts)
    print(xml)


if __name__ == "__main__":
    main()
