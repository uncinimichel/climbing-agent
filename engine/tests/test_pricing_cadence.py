"""Unit tests for driver.pricing_due — how often a live trip spends SerpApi
quota (SerpApi's own cache lasts 1h, so the daily cadence is ours). No network."""
from datetime import date, datetime, timedelta, timezone

from engine import driver

NOW = datetime(2026, 10, 20, 11, 0, tzinfo=timezone.utc)
FAR = date(2026, 11, 27)     # 38 days out
NEAR = date(2026, 10, 30)    # 10 days out


def _priced(hours_ago):
    return {"priced_at": (NOW - timedelta(hours=hours_ago)).isoformat(timespec="minutes")}


def test_never_priced_is_due():
    assert driver.pricing_due({}, FAR, NOW)
    assert driver.pricing_due({"priced_at": "garbage"}, FAR, NOW)


def test_far_out_reprices_every_three_days():
    assert not driver.pricing_due(_priced(24), FAR, NOW)
    assert not driver.pricing_due(_priced(48), FAR, NOW)
    assert driver.pricing_due(_priced(70), FAR, NOW)


def test_close_in_reprices_daily_but_not_on_same_day_rebuilds():
    assert driver.pricing_due(_priced(23), NEAR, NOW)
    assert not driver.pricing_due(_priced(3), NEAR, NOW)    # a push rebuild after the cron
