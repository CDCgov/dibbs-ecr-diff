from datetime import UTC, datetime, timedelta

import pytest
from core.datetime_utils import get_current_datetime
from pytest import approx


def test_get_current_datetime_rejects_invalid_fixed_datetime(monkeypatch) -> None:
    monkeypatch.setenv("DID_FIXED_DATE_TIME", "invalid")
    monkeypatch.setenv("ENV", "test")

    with pytest.raises(
        ValueError,
        match="DID_FIXED_DATE_TIME must be a valid ISO 8601 datetime",
    ):
        get_current_datetime()


def test_get_current_datetime_takes_valid_iso_string(monkeypatch) -> None:
    monkeypatch.setenv("DID_FIXED_DATE_TIME", "2026-08-25")
    monkeypatch.setenv("ENV", "test")

    now = get_current_datetime()

    assert now.year == 2026
    assert now.month == 8
    assert now.day == 25


def test_get_current_datetime_defaults_to_current_date_in_non_test_env(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ENV", "production")

    now = get_current_datetime()
    assert now == approx(datetime.now(UTC), abs=timedelta(seconds=1))
