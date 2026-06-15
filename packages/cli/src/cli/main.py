import argparse
import json
from pathlib import Path
from uuid import uuid4

from core import diff_xml
from core.augment import augment_eicr, create_augmentation_run
from core.models import Configuration, DiffingOptions
from lxml import etree

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
    diff_output_json = diff_output.model_dump_json(indent=2)
    print(diff_output_json)

    # TODO: refactor so XML is only parsed once
    parser = etree.XMLParser(remove_blank_text=True, huge_tree=True)
    eicr_root = etree.parse(opts.file2, parser).getroot()
    augmentation_run = create_augmentation_run(eicr_root)

    jurisdiction_id = str(uuid4())
    condition_grouper_uuid = uuid4()

    augmented_eicr_result = augment_eicr(
        eicr_root,
        augmentation_run,
        jurisdiction_id=jurisdiction_id,
        condition_grouper_uuid=condition_grouper_uuid,
        diff_output=diff_output)

    output_bytes = etree.tostring(
        eicr_root,
        pretty_print=True,
        xml_declaration=True,
        encoding="UTF-8",
    )

    print(f"Original document id: {augmented_eicr_result.original_doc_id}")
    print(f"Augmented document id: {augmented_eicr_result.augmented_doc_id}")

    out_path = Path("augmented_eicr_with_diff.xml")
    out_path.write_bytes(output_bytes)
    print(f"Wrote {out_path.resolve()} ({len(output_bytes)} bytes)")


if __name__ == "__main__":
    main()
