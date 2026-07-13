"""Unit tests for engine.flights.flex_alternatives — ±day whole-trip shifts
(decision #33 §Date flexibility). SerpApi is monkeypatched; no network."""
from datetime import date

from engine import flights
from engine.models import TripContext

VENUE = {"name": "Fair Head, NI", "travel": {"michel": {"mode": "fly", "to": "BFS"},
                                              "dan": {"mode": "local"}}}
TRAVELLERS = [
    {"key": "michel", "name": "Michel",
     "homes": [{"city": "London", "lat": 51.5, "lon": -0.13}], "airports": ["LGW", "LHR"]},
    {"key": "dan", "name": "Dan",
     "homes": [{"city": "Belfast", "lat": 54.6, "lon": -5.9}], "airports": ["BFS"]},
]
TODAY = date(2026, 7, 13)


def _ctx(flex_days, key=None):
    return TripContext(
        trip_name="t", target_start=date(2026, 7, 24), target_end=date(2026, 7, 28),
        venues=[VENUE], serpapi_key=key, travellers=TRAVELLERS, flex_days=flex_days,
        flights_cfg={"route": {"passengers": 1},
                     "combos": [{"out": "2026-07-24", "back": "2026-07-28", "nights": 4}]})


class CountingGuard:
    def __init__(self):
        self.spent = 0

    def can_spend(self, n=1):
        return True

    def record_spend(self, n=1):
        self.spent += n


def test_flex_off_returns_none():
    assert flights.flex_alternatives(VENUE, _ctx(0), today=TODAY) is None


def test_links_only_without_key():
    fx = flights.flex_alternatives(VENUE, _ctx(2), today=TODAY)
    assert set(fx) == {"michel"}                      # dan is local — no flights
    shifts = [a["shift"] for a in fx["michel"]]
    assert shifts == [-2, -1, 1, 2]                   # whole-trip shifts, no 0
    for a in fx["michel"]:
        assert "skyscanner" in a["book_url"] and "price" not in a
    assert fx["michel"][0]["out"] == "2026-07-22" and fx["michel"][0]["back"] == "2026-07-26"


def test_priced_with_key_and_quota_counted(monkeypatch):
    def fake_serp(dep, arr, out, back, pax, key):
        return {"mode": "fly", "to": arr, "options": [{"price": 100, "from": dep.split(",")[0],
                "to": arr, "dep": "x", "arr": "y", "stops": 0, "airline": "a"}],
                "view_url": f"https://g/{out}"}
    monkeypatch.setattr(flights, "serp_flights", fake_serp)
    guard = CountingGuard()
    fx = flights.flex_alternatives(VENUE, _ctx(1, key="k"), quota_guard=guard, today=TODAY)
    assert guard.spent == 2                           # ±1 for the one flying traveller
    assert all(a["price"] == 100 and a["view_url"].startswith("https://g/")
               for a in fx["michel"])


def test_prev_flex_reused_when_lookup_fails(monkeypatch):
    monkeypatch.setattr(flights, "serp_flights", lambda *a: None)
    prev = {"michel": [{"shift": -1, "price": 88, "view_url": "https://old"},
                       {"shift": 1, "price": None}]}
    fx = flights.flex_alternatives(VENUE, _ctx(1, key="k"), prev_flex=prev, today=TODAY)
    m = {a["shift"]: a for a in fx["michel"]}
    assert m[-1]["price"] == 88 and m[-1]["cached"] and m[-1]["view_url"] == "https://old"
    assert "price" not in m[1]                        # None in prev → stays link-only


def test_past_departures_skipped():
    fx = flights.flex_alternatives(VENUE, _ctx(2), today=date(2026, 7, 22))
    shifts = [a["shift"] for a in fx["michel"]]
    assert shifts == [-1, 1, 2]                       # −2 would depart on/before 'today'
