import argparse
import json
from pathlib import Path

from core import diff_xml
from core.models import Configuration, DiffingOptions

DEFAULT_CONFIG_PATH = Path(__file__).parent / "default_config.json"


def main() -> None:
    """CLI entrypoint."""
    ap = argparse.ArgumentParser(description="Diff two CDA/eICR XML files.")
    ap.add_argument("file1", help="Original CDA/eICR XML (before)")
    ap.add_argument("file2", help="New CDA/eICR XML (after)")
    ap.add_argument(
        "-c", "--config", help="Path to configuration", default=str(DEFAULT_CONFIG_PATH)
    )

    args = ap.parse_args()
    opts = DiffingOptions(**vars(args))

    with open(opts.config) as f:
        config = Configuration(**json.load(f))

    diff_output = diff_xml(opts, config)
    print(diff_output)


if __name__ == "__main__":
    main()
