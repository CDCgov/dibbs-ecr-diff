import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from core import diff_xml
from core.configurations import load_configuration
from core.models import Configuration, DiffingOptions

DEFAULT_CONFIGURATION_FILE = "aphl_baseline.json"


def main() -> None:
    """CLI entrypoint."""
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")

    ap = argparse.ArgumentParser(description="Diff two CDA/eICR XML files.")
    ap.add_argument("file1", help="Original CDA/eICR XML (before)")
    ap.add_argument("file2", help="New CDA/eICR XML (after)")
    ap.add_argument(
        "-c",
        "--config",
        help="Path to configuration (default: bundled APHL baseline)",
    )
    ap.add_argument(
        "-o",
        "--output-diff-file",
        help="Path to output diff JSON",
        default=f"{timestamp}_diff_output.json",
    )

    args = ap.parse_args()
    opts = DiffingOptions(**vars(args))

    if opts.config is None:
        config = load_configuration(DEFAULT_CONFIGURATION_FILE)
    else:
        with open(opts.config) as f:
            config = Configuration(**json.load(f))

    diff_output = diff_xml(opts, config)
    diff_output_json = diff_output.model_dump_json(indent=2)

    if opts.output_diff_file:
        json_out_path = Path(opts.output_diff_file)
        json_out_path.write_text(diff_output_json, encoding="utf-8")
        print(f"Wrote {json_out_path.resolve()}")


if __name__ == "__main__":
    main()
