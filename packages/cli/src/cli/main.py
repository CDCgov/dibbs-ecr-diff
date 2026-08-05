import argparse
import json
from pathlib import Path

from core import diff_xml
from core.augment import augment_eicr_in_place, create_augmentation_run
from core.configurations import load_configuration
from core.models import Configuration, DiffingOptions
from core.performance import measure_time
from lxml import etree

DEFAULT_CONFIGURATION_FILE = "aphl_baseline.json"
DEFAULT_OUTPUT_DIRECTORY = "output"

DIFF_OUTPUT_FILENAME = "diff_output.json"
EICR_OUTPUT_FILENAME = "augmented_eicr_with_diff.xml"


def main() -> None:
    """CLI entrypoint."""
    ap = argparse.ArgumentParser(description="Diff two CDA/eICR XML files.")
    ap.add_argument("file1", help="Original CDA/eICR XML (before)")
    ap.add_argument("file2", help="New CDA/eICR XML (after)")
    ap.add_argument(
        "-c",
        "--config",
        help="Path to configuration (default: " + DEFAULT_CONFIGURATION_FILE,
    )
    ap.add_argument(
        "-o",
        "--output-dir",
        help="Path to directory for output files (default: " + DEFAULT_OUTPUT_DIRECTORY,
    )

    args = ap.parse_args()
    opts = DiffingOptions(**vars(args))

    if opts.config is None:
        config = load_configuration(DEFAULT_CONFIGURATION_FILE)
    else:
        with open(opts.config) as f:
            config = Configuration(**json.load(f))

    if opts.output_dir is None:
        output_dir = Path(DEFAULT_OUTPUT_DIRECTORY)
    else:
        output_dir = Path(opts.output_dir)

    parser = etree.XMLParser(remove_blank_text=True, huge_tree=True)

    with measure_time("Parse XML files"):
        before_tree = etree.parse(opts.file1, parser)
        after_tree = etree.parse(opts.file2, parser)

    diff_output = diff_xml(before_tree, after_tree, config)

    eicr_root = after_tree.getroot()
    augmentation_run = create_augmentation_run(eicr_root)

    # TODO: extract jurisdiction id
    jurisdiction_id = "12345678-1234-5678-1234-567812345678"

    augmented_eicr_result = augment_eicr_in_place(
        eicr_root,
        augmentation_run,
        jurisdiction_id=jurisdiction_id,
        diff_output=diff_output,
    )

    print(f"Original document id: {augmented_eicr_result.original_doc_id}")
    print(f"Augmented document id: {augmented_eicr_result.augmented_doc_id}")

    output_dir.mkdir(parents=True, exist_ok=True)

    diff_output_json = diff_output.model_dump_json(indent=2)

    json_out_path = output_dir / DIFF_OUTPUT_FILENAME
    json_out_path.write_text(diff_output_json, encoding="utf-8")
    print(f"Wrote {json_out_path.resolve()}")

    eicr_output_bytes = etree.tostring(
        eicr_root,
        pretty_print=True,
        xml_declaration=True,
        encoding="UTF-8",
    )

    eicr_out_path = output_dir / EICR_OUTPUT_FILENAME
    eicr_out_path.write_bytes(eicr_output_bytes)
    print(f"Wrote {eicr_out_path.resolve()} ({len(eicr_output_bytes)} bytes)")


if __name__ == "__main__":
    main()
