import pytest
from core.datetime_utils import get_current_datetime


def test_get_current_datetime_rejects_invalid_fixed_datetime(monkeypatch) -> None:
    monkeypatch.setenv("DID_FIXED_DATE_TIME", "invalid")

    with pytest.raises(
        ValueError,
        match="DID_FIXED_DATE_TIME must be a valid ISO 8601 datetime",
    ):
        get_current_datetime()
