"""Datetime utilities."""

import os
from datetime import UTC, datetime


def get_current_datetime() -> datetime:
    """Return the current UTC datetime or the configured fixed datetime."""
    fixed_datetime = os.getenv("DID_FIXED_DATE_TIME")
    if fixed_datetime is None:
        return datetime.now(UTC)

    value = datetime.fromisoformat(fixed_datetime)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
