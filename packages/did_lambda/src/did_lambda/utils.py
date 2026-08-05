"""Utilities for the Difference in Docs Lambda."""

from datetime import UTC, datetime
from io import BytesIO

from lxml import etree

parser = etree.XMLParser(remove_blank_text=True, huge_tree=True)


class InfraError(Exception):
    """Raised for failures that should trigger an automated SQS retry or DLQ."""


def parse_xml(source: bytes) -> etree._ElementTree:
    """Parse an XML file using its filepath or bytes."""
    return etree.parse(BytesIO(source), parser)


def get_timestamp() -> str:
    """Generate a new ISO-8601 timestamp."""
    return datetime.now(UTC).isoformat()


def persistence_id_from_key(key: str) -> str:
    """Strip the first S3 key segment (prefix) to leave the persistence_id.

    AIMS form: YYYY/MM/DD/{uuid}
    Example: DIDInput/2026/07/14/19d4812b-fc1d-471a-8872-6d5edd1714ff
    → 2026/07/14/19d4812b-fc1d-471a-8872-6d5edd1714ff
    """
    parts = key.strip("/").split("/", 1)
    if len(parts) != 2 or not parts[1]:
        raise InfraError(f"S3 key has no persistence_id after prefix: {key}")
    return parts[1]


def jurisdiction_id_from_key(persistence_id: str, key: str) -> str:
    """Extract the jurisdiction ID between the persistence ID and filename."""
    persistence_id_part = f"/{persistence_id.strip('/')}/"
    parts = key.strip("/").split(persistence_id_part, 1)

    if len(parts) != 2:
        raise InfraError(f"S3 key does not contain persistence_id: {key}")

    jurisdiction_id_parts = parts[1].split("/")[:-1]
    return "/".join(jurisdiction_id_parts)


def get_did_output_key(root_prefix: str, source_key: str) -> str:
    """Convert an S3 key into a DIDOutput-prefixed key."""
    output_prefix = get_did_output_prefix(root_prefix, source_key)
    return f"{output_prefix}/{get_key_basename(source_key)}"


def get_did_output_prefix(root_prefix: str, source_key: str) -> str:
    """Extract an S3 key prefix from a DIDInput S3 key."""
    parts = source_key.strip("/").split("/")
    if len(parts) <= 2:
        raise InfraError(f"S3 key has nothing after prefix: {source_key}")
    return f"{root_prefix}{'/'.join(parts[1:-1])}"


def get_key_basename(source_key: str) -> str:
    """Get the basename of an S3 key."""
    key = source_key.strip("/")
    if not key:
        raise InfraError(f"Invalid S3 key: {source_key}")
    return key.rsplit("/", 1)[-1]
