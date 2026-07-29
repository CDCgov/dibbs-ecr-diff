import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from core import diff_xml
from core.models import Configuration, DiffingOptions

DEFAULT_CONFIG_PATH = Path(__file__).parent / "cste_config.json"


def main() -> None:
    """CLI entrypoint."""
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")

    ap = argparse.ArgumentParser(description="Diff two CDA/eICR XML files.")
    ap.add_argument("file1", help="Original CDA/eICR XML (before)")
    ap.add_argument("file2", help="New CDA/eICR XML (after)")
    ap.add_argument(
        "-c", "--config", help="Path to configuration", default=str(DEFAULT_CONFIG_PATH)
    )
    ap.add_argument(
        "-o",
        "--output-diff-file",
        help="Path to output diff JSON",
        default=f"{timestamp}_diff_output.json",
    )

    args = ap.parse_args()
    opts = DiffingOptions(**vars(args))

    config_path = str(DEFAULT_CONFIG_PATH) if opts.config is None else opts.config
    with open(config_path) as f:
        config = Configuration(**json.load(f))

    diff_output = diff_xml(opts, config)
    diff_output_json = diff_output.model_dump_json(indent=2)

    if opts.output_diff_file:
        json_out_path = Path(opts.output_diff_file)
        json_out_path.write_text(diff_output_json, encoding="utf-8")
        print(f"Wrote {json_out_path.resolve()}")


if __name__ == "__main__":
    main()
