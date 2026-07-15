"""Hourly day/night rain split (2026-07-15): rain is charged by WHEN it falls —
climbing-window rain at full price, night-before rain discounted by drying
speed — and every hour/tide timestamp stays in the venue's OWN timezone
(Open-Meteo is fetched with timezone=auto; nothing may re-interpret those
strings as UTC or London time)."""
from engine import weather


def _forecast(hourly_precip, hourly_prob=None):
    """Minimal 2-day forecast response; hourly_precip keyed by (ISO date, hour)."""
    days = ["2026-07-24", "2026-07-25"]
    times, pre, prob = [], [], []
    for d in days:
        for h in range(24):
            times.append(f"{d}T{h:02d}:00")
            pre.append(hourly_precip.get((d, h), 0.0))
            prob.append((hourly_prob or {}).get((d, h), 0))
    out = {
        "daily": {"time": days, "temperature_2m_max": [16, 16]},
        "hourly": {"time": times, "precipitation": pre},
    }
    if hourly_prob is not None:
        out["hourly"]["precipitation_probability"] = prob
    return out


def test_metrics_split_day_vs_night_before():
    # 2 mm on the 24th at 22:00 + 3 mm on the 25th at 02:00 = the 25th's "night
    # before"; 1.5 mm at noon on the 24th is climbing-window rain on the 24th.
    met = weather.forecast_metrics(_forecast({
        ("2026-07-24", 12): 1.5, ("2026-07-24", 22): 2.0, ("2026-07-25", 2): 3.0}))
    assert met["2026-07-24"]["rain_day"] == 1.5
    assert met["2026-07-24"]["wet_hrs_day"] == 1
    assert met["2026-07-25"]["rain_day"] == 0.0
    assert met["2026-07-25"]["rain_night"] == 5.0
    assert met["2026-07-25"]["wet_hrs_day"] == 0


def test_prob_day_is_climbing_window_max():
    met = weather.forecast_metrics(_forecast(
        {}, hourly_prob={("2026-07-24", 3): 90, ("2026-07-24", 14): 35}))
    # the 90% at 03:00 is outside climbing hours — the day reads 35%
    assert met["2026-07-24"]["prob_day"] == 35


def test_night_rain_beats_same_mm_day_rain():
    day = {"rain_day": 4.0, "rain_night": 0.0, "wet_hrs_day": 3, "dry_f": 1.0}
    night = {"rain_day": 0.0, "rain_night": 4.0, "wet_hrs_day": 0, "dry_f": 1.0}
    s_day = weather.day_score(61, 4.0, 60, day)
    s_night = weather.day_score(61, 4.0, 60, night)
    assert s_night > s_day
    # the code-61 cap fired for the wet day but NOT for the dry-day/wet-night one
    assert s_day <= 25 < s_night


def test_storm_cap_skipped_when_climbing_hours_dry():
    night = {"rain_day": 0.0, "rain_night": 6.0, "wet_hrs_day": 0, "dry_f": 1.0}
    assert weather.day_score(95, 6.0, 70, night) > 15
    wet = {"rain_day": 6.0, "rain_night": 0.0, "wet_hrs_day": 4, "dry_f": 1.0}
    assert weather.day_score(95, 6.0, 70, wet) <= 15


def test_slow_drying_rock_pays_more_for_night_rain():
    fast = {"rain_day": 0.0, "rain_night": 8.0, "wet_hrs_day": 0, "dry_f": 0.7}
    slow = {"rain_day": 0.0, "rain_night": 8.0, "wet_hrs_day": 0, "dry_f": 1.4}
    assert weather.day_score(61, 8.0, 40, fast) > weather.day_score(61, 8.0, 40, slow)


def test_no_split_falls_back_to_daily_totals():
    # pre-split metrics (e.g. an old cache with no hourly precip) keep the old
    # behaviour: full daily mm + the unconditional rain cap
    m = {"precip_hours": 5, "dry_f": 1.0}
    assert weather.day_score(61, 4.0, 60, m) <= 25


def test_hourly_by_date_uses_local_hour_as_index():
    d = {"hourly": {
        "time": ["2026-07-24T00:00", "2026-07-24T15:00"],
        "temperature_2m": [11.6, 19.4], "precipitation": [0.0, 1.23],
        "precipitation_probability": [5, 66], "weathercode": [1, 61],
        "windspeed_10m": [7.4, 22.6], "wind_gusts_10m": [12.0, 41.0],
        "is_day": [0, 1]}}
    hby = weather.hourly_by_date(d)
    day = hby["2026-07-24"]
    assert len(day) == 24 and day[1] is None
    assert day[0] == [12, 0.0, 5, 1, 7, 12, 0]
    assert day[15] == [19, 1.2, 66, 61, 23, 41, 1]


def test_tide_extremes_keep_venue_local_times(monkeypatch):
    # A synthetic tide curve whose high water sits exactly on the 03:00 LOCAL
    # sample: the extreme must come back as "03:00", verbatim from the local
    # ISO strings the marine API returns with timezone=auto — never shifted
    # through UTC/London.
    times = [f"2026-07-24T{h:02d}:00" for h in range(24)]
    levels = [-abs(h - 3) * 0.5 + 2.0 for h in range(24)]  # peak at h=3
    monkeypatch.setattr(weather, "tides",
                        lambda lat, lon: {"hourly": {"time": times,
                                                     "sea_level_height_msl": levels}})
    out = weather.tide_extremes(0.0, 0.0)
    assert out["2026-07-24"][0]["k"] == "H"
    assert out["2026-07-24"][0]["t"] == "03:00"
