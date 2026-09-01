"""Datetime utilities."""

import os
from datetime import UTC, datetime


def get_current_datetime() -> datetime:
    """Return the current UTC datetime or the configured fixed datetime.

    Valid `DID_FIXED_DATE_TIME` strings:
    - 2026-08-25T12:34:56+00:00
    - 2026-08-25T08:34:56-04:00
    - 2026-08-25T12:34:56.123456
    - 2026-08-25 12:34:56
    - 2026-08-25
    """
    fixed_datetime = os.getenv("DID_FIXED_DATE_TIME")
    environment = os.getenv("ENV")

    if isinstance(fixed_datetime, str) and environment != "production":
        fixed_datetime = fixed_datetime.strip()
    if not fixed_datetime:
        return datetime.now(UTC)

    try:
        value = datetime.fromisoformat(fixed_datetime)
    except ValueError as exc:
        raise ValueError(
            "DID_FIXED_DATE_TIME must be a valid ISO 8601 datetime"
        ) from exc

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
