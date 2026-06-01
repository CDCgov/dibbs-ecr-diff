import argparse

from core import diff_xml
from core.models import DiffingOptions


def main() -> None:
    """CLI entrypoint."""
    ap = argparse.ArgumentParser(description="Diff two CDA/eICR XML files.")
    ap.add_argument("file1", help="Original CDA/eICR XML (before)")
    ap.add_argument("file2", help="New CDA/eICR XML (after)")

    args = ap.parse_args()
    opts = DiffingOptions(**vars(args))

    print(opts)
    _xml = diff_xml(opts)
    print(_xml)


if __name__ == "__main__":
    main()
