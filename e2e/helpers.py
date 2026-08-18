"""Helpers for local end-to-end tests."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from lxml import etree

HL7_NAMESPACE = "urn:hl7-org:v3"

parser = etree.XMLParser(remove_blank_text=True, huge_tree=True)


def send_input_files(
    s3_client: Any,
    bucket_name: str,
    eicr_path: Path,
    rr_path: Path,
) -> tuple[str, dict[str, Any], str]:
    """Send one eICR/RR pair and its manifest to LocalStack S3."""
    eicr_root = etree.parse(eicr_path, parser).getroot()

    # parse the set_id from the eICR
    set_id = eicr_root.find(f"{{{HL7_NAMESPACE}}}setId").attrib["root"]

    # parse the version_number from the eICR
    version_number = int(
        eicr_root.find(f"{{{HL7_NAMESPACE}}}versionNumber").attrib["value"]
    )

    persistence_id = f"{datetime.now(UTC):%Y/%m/%d}/{uuid4()}"
    base_key = f"RefinerOutputV2/{persistence_id}/SDDH/COVID19"
    eicr_key = f"{base_key}/{eicr_path.name}"
    rr_key = f"{base_key}/{rr_path.name}"

    s3_client.put_object(Bucket=bucket_name, Key=eicr_key, Body=eicr_path.read_bytes())
    s3_client.put_object(Bucket=bucket_name, Key=rr_key, Body=rr_path.read_bytes())

    manifest = {
        "Files": [
            {
                "eicr": eicr_key,
                "rr": rr_key,
                "setId": set_id,
                "versionNumber": version_number,
                "jurisdictions": ["SDDH"],
            }
        ]
    }
    manifest_key = f"DIDInput/{persistence_id}"
    s3_client.put_object(
        Bucket=bucket_name,
        Key=manifest_key,
        Body=json.dumps(manifest).encode(),
    )

    return manifest_key, manifest, persistence_id
