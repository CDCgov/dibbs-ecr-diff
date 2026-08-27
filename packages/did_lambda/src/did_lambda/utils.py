"""Utilities for the Difference in Docs Lambda."""

from datetime import UTC, datetime


class ApplicationError(Exception):
    """Raised for Difference in Docs application errors."""


class InfraError(Exception):
    """Raised for failures that should trigger an automated SQS retry or DLQ."""


def get_timestamp() -> datetime:
    """Generate a new ISO-8601 timestamp."""
    return datetime.now(UTC)


def persistence_id_from_manifest_key(key: str) -> str:
    """Strip the first S3 key segment (prefix) form manifest key to leave the persistence_id.

    AIMS form: YYYY/MM/DD/{uuid}
    Example: DIDInput/2026/07/14/19d4812b-fc1d-471a-8872-6d5edd1714ff
    → 2026/07/14/19d4812b-fc1d-471a-8872-6d5edd1714ff
    """
    parts = key.strip("/").split("/", 1)
    if len(parts) != 2 or not parts[1]:
        raise ValueError(f"S3 key has no persistence_id after prefix: {key}")
    return parts[1]


def get_did_output_key(
    *, root_prefix: str, persistence_id: str, source_key: str, fallback_basename: str
) -> str:
    """Convert an S3 key into a DIDOutput-prefixed key.

    Examples:
    RefinerOutputV2/{persistence_id}/SDDH/COVID19/cda_eicr_1.xml
        -> DIDOutputV2/{persistence_id}/SDDH/COVID19/cda_eicr_1.xml

    eCRMessageV2/{persistence_id} -> DIDOutputV2/{persistence_id}/{fallback_basename}
    """
    output_path = get_did_output_path(root_prefix, persistence_id, source_key)

    # ex: "eCRMessageV2/2026/08/17/abc-123" -> "2026/08/17/abc-123"
    source_path = source_key.strip("/").split("/", 1)[-1]

    # handle s3 keys like `eCRMessageV2/<persistence_id>`
    if source_path == persistence_id.strip("/"):
        return f"{output_path}/{fallback_basename}"

    basename = source_path.rsplit("/", 1)[-1]
    return f"{output_path}/{basename}"


def get_did_output_path(
    root_prefix: str,
    persistence_id: str,
    source_key: str,
) -> str:
    """Convert an S3 key into a DIDOutput-prefixed parent path.

    RefinerOutputV2/<persistence_id>/SDDH/COVID19/file.xml -> DIDOutputV2/<persistence_id>/SDDH/COVID19
    eCRMessageV2/<persistence_id> -> DIDOutputV2/<persistence_id>
    """
    # every part after DIDInput/
    # ex: ['2026', '08', '06', '<uuid>', 'SDDH', 'COVID19', 'cda_eicr_3.xml']
    source_parts = source_key.strip("/").split("/")[1:]

    persistence_id_parts = persistence_id.strip("/").split("/")

    # check if source_key begins with the persistence_id
    after_persistence_idx = len(persistence_id_parts)
    if source_parts[:after_persistence_idx] != persistence_id_parts:
        raise ValueError("Source key does not contain persistence ID")

    parts = source_parts if source_parts == persistence_id_parts else source_parts[:-1]
    return f"{root_prefix}{'/'.join(parts)}"


def get_key_basename(source_key: str) -> str:
    """Get the basename of an S3 key."""
    key = source_key.strip("/")
    if not key:
        raise ValueError(f"Invalid S3 key: {source_key}")
    return key.rsplit("/", 1)[-1]
