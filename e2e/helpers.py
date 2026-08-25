"""Helpers for local end-to-end tests."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from lxml import etree

HL7_NAMESPACE = "urn:hl7-org:v3"
INPUT_PREFIX = "DIDInput/"
COMPLETE_PREFIX = "DIDCompleteV2/"

parser = etree.XMLParser(remove_blank_text=True, huge_tree=True)


class UploadType(StrEnum):
    """Types of eICR/RR pairs that can be uploaded."""

    REFINED = "refined"
    UNREFINED = "unrefined"
    REMAINDER_RR = "remainder_rr"


@dataclass(frozen=True)
class Pair:
    """An eICR/RR pair."""

    eicr: str
    rr: str
    upload_type: UploadType = UploadType.REFINED
    jurisdiction: str = "SDDH"
    condition: str = "COVID19"


@dataclass
class ManifestFile:
    """File metadata from an input or complete manifest."""

    rr: str
    setId: str
    versionNumber: int
    jurisdictions: list[str]
    eicr: str | None = None
    originalRr: str | None = None
    eicr_diff_output: str | None = None
    is_actionable: bool = False


@dataclass(frozen=True)
class ManifestMetadata:
    """Metadata for a manifest in the local pipeline."""

    persistence_id: str
    key: str
    files: list[ManifestFile]


def build_persistence_id() -> str:
    """Build a persistence ID."""
    return f"{datetime.now(UTC):%Y/%m/%d}/{uuid4()}"


class Uploader:
    """Uploader to upload assets from e2e/assets + build manifest files."""

    def __init__(
        self,
        s3_client: Any,
        bucket_name: str,
        assets_dir: Path,
        persistence_id_factory: Callable[[], str] = build_persistence_id,
    ) -> None:
        """Intialize an uploader."""
        self.s3 = s3_client
        self.bucket_name = bucket_name
        self.assets_dir = assets_dir
        self.persistence_id_factory = persistence_id_factory

    def wait_until_ready(self) -> None:
        """Wait until the test bucket exists."""
        self.s3.get_waiter("bucket_exists").wait(
            Bucket=self.bucket_name,
            WaiterConfig={"Delay": 1, "MaxAttempts": 10},
        )

    def read_object(self, key: str) -> str:
        """Read file frfom S3."""
        response = self.s3.get_object(Bucket=self.bucket_name, Key=key)
        return response["Body"].read().decode()

    def send_manifest(
        self, pairs: list[Pair]
    ) -> tuple[ManifestMetadata, ManifestMetadata, str]:
        """Upload one manifest and wait for the completed manifest."""
        persistence_id = self.persistence_id_factory()
        manifest_files = []
        objects: dict[str, Path] = {}  # S3 Key -> File Path

        for pair in pairs:
            eicr_path = self.assets_dir / pair.eicr
            rr_path = self.assets_dir / pair.rr

            if not eicr_path.is_file() or not rr_path.is_file():
                raise Exception(f"Invalid files for eICR pair: {pair}")

            # parse setId and versionNumber from eICR file
            set_id, version_number = self._get_metadata(eicr_path)

            # attempt to parse RR for validation
            self._parse_xml(rr_path)

            # build eICR/RR keys
            eicr_key, rr_key = self._build_pair_keys(
                persistence_id, pair, eicr_path.name, rr_path.name
            )

            # build objects dict to upload to S3
            for key, path in ((eicr_key, eicr_path), (rr_key, rr_path)):
                objects[key] = path

            manifest_files.append(
                {
                    "eicr": eicr_key,
                    "rr": rr_key,
                    "originalRr": None,
                    "setId": set_id,
                    "versionNumber": version_number,
                    "jurisdictions": [pair.jurisdiction],
                }
            )

        # upload all individual eICR/RR pairs
        for key, path in objects.items():
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=path.read_bytes(),
                ContentType="application/xml",
            )

        # upload DIDInput/ manifest
        did_input_manifest_key = f"{INPUT_PREFIX}{persistence_id}"
        manifest = {"Files": manifest_files}
        self.s3.put_object(
            Bucket=self.bucket_name,
            Key=did_input_manifest_key,
            Body=json.dumps(manifest, indent=2).encode(),
            ContentType="application/json",
        )

        input_manifest = self._wait_for_manifest(did_input_manifest_key, persistence_id)

        # wait for complete manifest to be written
        did_complete_manifest_key = f"{COMPLETE_PREFIX}{persistence_id}"
        complete_manifest = self._wait_for_manifest(
            did_complete_manifest_key, persistence_id
        )

        return input_manifest, complete_manifest, persistence_id

    def _wait_for_manifest(self, key: str, persistence_id: str) -> ManifestMetadata:
        """Wait for a manifest and return its metadata."""
        self.s3.get_waiter("object_exists").wait(
            Bucket=self.bucket_name,
            Key=key,
            WaiterConfig={"Delay": 1, "MaxAttempts": 30},
        )
        manifest = json.loads(self.read_object(key))
        return ManifestMetadata(
            persistence_id=persistence_id,
            key=key,
            files=[ManifestFile(**entry) for entry in manifest["Files"]],
        )

    def _get_metadata(self, eicr_path: Path) -> tuple[str, int]:
        eicr_root = self._parse_xml(eicr_path)
        set_id_el = eicr_root.find(f"{{{HL7_NAMESPACE}}}setId")
        version_el = eicr_root.find(f"{{{HL7_NAMESPACE}}}versionNumber")

        set_id = set_id_el.get("root") if set_id_el is not None else None
        version = version_el.get("value") if version_el is not None else None

        if not set_id or version is None:
            raise ValueError(f"Missing setId or versionNumber in {eicr_path}")

        return set_id, int(version)

    def _build_pair_keys(
        self,
        persistence_id: str,
        pair: Pair,
        eicr_name: str,
        rr_name: str,
    ) -> tuple[str, str]:
        if pair.upload_type is UploadType.REFINED:
            base_key = (
                f"RefinerOutputV2/{persistence_id}/{pair.jurisdiction}/{pair.condition}"
            )
            return f"{base_key}/{eicr_name}", f"{base_key}/{rr_name}"
        elif pair.upload_type is UploadType.UNREFINED:
            return (
                f"eCRMessageV2/{persistence_id}",
                f"RRMessageV2/{persistence_id}",
            )
        elif pair.upload_type is UploadType.REMAINDER_RR:
            return (
                f"eCRMessageV2/{persistence_id}",
                f"RefinerOutputV2/{persistence_id}/{pair.jurisdiction}/unrefined_rr/refined_rr.xml",
            )

        raise Exception(f"Invalid upload type: {pair.upload_type}")

    def _parse_xml(self, path: Path) -> etree._Element:
        try:
            return etree.parse(path, parser).getroot()
        except etree.XMLSyntaxError as exc:
            raise Exception(f"Invalid XML file: {path}") from exc
