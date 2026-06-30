import uuid
import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from core import diff_xml
from core.augment import augment_eicr, create_augmentation_run
from core.models import Configuration, DiffingOptions
from lxml import etree

DEFAULT_CONFIG_PATH = Path(__file__).parent / "default_config.json"


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

    with open(opts.config) as f:
        config = Configuration(**json.load(f))

    diff_output = diff_xml(opts, config)
    diff_output_json = diff_output.model_dump_json(indent=2)

    if opts.output_diff_file:
        json_out_path = Path(opts.output_diff_file)
        json_out_path.write_text(diff_output_json, encoding="utf-8")
        print(f"Wrote {json_out_path.resolve()}")

    parser = etree.XMLParser(remove_blank_text=True, huge_tree=True)
    eicr_root = etree.parse(opts.file2, parser).getroot()
    augmentation_run = create_augmentation_run(eicr_root)

    # TODO: extract jurisdiction id
    jurisdiction_id = "12345678-1234-5678-1234-567812345678"
    # TODO: determine whether we can remove condition_grouper_uuid
    condition_grouper_uuid = uuid.UUID("22345678-1234-5678-1234-567812345678")

    augmented_eicr_result = augment_eicr(
        eicr_root,
        augmentation_run,
        jurisdiction_id=jurisdiction_id,
        condition_grouper_uuid=condition_grouper_uuid,
        diff_output=diff_output,
    )

    output_bytes = etree.tostring(
        eicr_root,
        pretty_print=True,
        xml_declaration=True,
        encoding="UTF-8",
    )

    print(f"Original document id: {augmented_eicr_result.original_doc_id}")
    print(f"Augmented document id: {augmented_eicr_result.augmented_doc_id}")

    eicr_out_path = Path("augmented_eicr_with_diff.xml")
    eicr_out_path.write_bytes(output_bytes)
    print(f"Wrote {eicr_out_path.resolve()} ({len(output_bytes)} bytes)")


if __name__ == "__main__":
    main()
