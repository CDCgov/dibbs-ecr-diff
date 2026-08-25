from datetime import UTC, datetime

from core.datetime_utils import get_current_datetime


def test_get_current_datetime_returns_current_utc_datetime(monkeypatch) -> None:
    monkeypatch.delenv("DID_FIXED_DATE_TIME", raising=False)
    before = datetime.now(UTC)

    value = get_current_datetime()

    assert before <= value <= datetime.now(UTC)


def test_get_current_datetime_returns_fixed_datetime_in_utc(monkeypatch) -> None:
    monkeypatch.setenv("DID_FIXED_DATE_TIME", "2026-08-25T12:34:56-04:00")

    value = get_current_datetime()

    assert value == datetime(2026, 8, 25, 16, 34, 56, tzinfo=UTC)


def test_get_current_datetime_treats_naive_fixed_datetime_as_utc(monkeypatch) -> None:
    monkeypatch.setenv("DID_FIXED_DATE_TIME", "2026-08-25T12:34:56")

    value = get_current_datetime()

    assert value == datetime(2026, 8, 25, 12, 34, 56, tzinfo=UTC)
