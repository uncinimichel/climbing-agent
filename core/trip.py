"""TripContext: the parameterized replacement for update_report.py's module-level
trip globals (TRIP_NAME, TARGET_START/END, FLIGHTS_CFG, ORIGIN, REP, ...).

Every value that used to be read from a module global at import time is now
either a field on TripContext (venues, flights_cfg, dates, serpapi_key) or a
derived property computed from those fields (graph window, rep combo, period
label) — so the same object can represent the one hardcoded NI trip today, or
an arbitrary user-defined trip tomorrow.

Travellers are data (decision #33 M2): TripContext.travellers carries the
trips.json registry entries ({key, name, homes, airports}) and every consumer
(flights.py, scoring.py's distance signal, render.py's pills/flight cards/
markdown) iterates them — no hardcoded traveller keys anywhere. When built
without a registry (legacy from_files path used by fetch_env/backtest), a
minimal traveller list is synthesized from flights.json's route
traveller_origins/traveller_coords.

Sport-agnostic: a trip has dates, travellers, venues and a budget for flights
whether it is a climbing, ski or golf trip. What "a good venue" means belongs to
the domain (domains/<sport>/), and so do the composite weights and the ranking
preferences — see NeutralPreferences below.
"""
from dataclasses import dataclass, field
from functools import cached_property
from datetime import date, timedelta


def md_range(start, end):
    """Set of (month, day) tuples covered by [start, end] inclusive — so window
    logic keeps working when a window straddles a month boundary."""
    out, d = set(), start
    while d <= end:
        out.add((d.month, d.day))
        d += timedelta(days=1)
    return out


def period_label(a, b):
    """Human name for a date window, derived from the dates ("late July",
    "early August", or "late July–early August" across months)."""
    def part(d):
        seg = "early" if d.day <= 10 else "mid" if d.day <= 20 else "late"
        return f"{seg} {d:%B}"
    pa, pb = part(a), part(b)
    return pa if pa == pb else f"{pa}–{pb}"


def short_name(name):
    return name.split("(")[0].split(",")[0].strip()


DEFAULT_CLIMO_YEARS = [2021, 2022, 2023, 2024]


class NeutralPreferences:
    """The default `prefs` on a trip: every ranking knob neutral.

    What knobs even EXIST is a domain question — climbing has heat tolerance and
    difficulty spread, golf would have wind tolerance and green speed — so core
    does not enumerate them. It just guarantees that reading any of them before
    a user has expressed a preference returns 1.0, i.e. "weight this the same as
    everything else". Domains ship their own dataclass (see
    domains/climbing/preferences.py) for the day a preferences UI writes into it."""

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return 1.0

    def __repr__(self):
        return "NeutralPreferences()"


@dataclass
class TripContext:
    trip_name: str
    target_start: date
    target_end: date
    venues: list
    flights_cfg: dict
    serpapi_key: str | None = None
    top_n_flights: int = 4
    climo_years: list = field(default_factory=lambda: list(DEFAULT_CLIMO_YEARS))
    prefs: object = field(default_factory=NeutralPreferences)
    # trips.json traveller entries: [{key, name, homes: [{city, lat, lon}],
    # airports: [IATA...]}, ...]. None → synthesized from flights_cfg (legacy).
    travellers: list | None = None
    # ± days the whole trip may shift for cheaper flights/stays (trips.json
    # flex_days, decision #33 §Date flexibility). 0 = exact dates only.
    flex_days: int = 0

    @property
    def graph_start(self):
        return self.target_start - timedelta(days=2)

    @property
    def graph_end(self):
        return self.target_end + timedelta(days=2)

    @property
    def graph_md(self):
        return md_range(self.graph_start, self.graph_end)

    @property
    def trip_md(self):
        return md_range(self.target_start, self.target_end)

    @property
    def period_lbl(self):
        return period_label(self.target_start, self.target_end)

    @property
    def trip_days(self):
        return (self.target_end - self.target_start).days + 1

    @property
    def rep_combo(self):
        return max(self.flights_cfg["combos"], key=lambda c: c["nights"])

    @property
    def rep_out_lbl(self):
        return f"{date.fromisoformat(self.rep_combo['out']):%a %d %b}"

    @property
    def rep_back_lbl(self):
        return f"{date.fromisoformat(self.rep_combo['back']):%a %d %b}"

    @property
    def combo_labels(self):
        return ", ".join(f"{c['out'][5:]}→{c['back'][5:]} ({c['nights']}n)"
                          for c in self.flights_cfg["combos"])

    @cached_property
    def travellers_norm(self):
        """The traveller list every consumer iterates. trips.json entries when
        present; otherwise synthesized from flights.json's route
        traveller_origins/traveller_coords (legacy from_files path — keys
        starting with '_', e.g. a JSON _comment, are skipped)."""
        if self.travellers:
            return self.travellers
        route = (self.flights_cfg or {}).get("route") or {}
        to = {k: v for k, v in (route.get("traveller_origins") or {}).items()
              if not k.startswith("_")}
        tc = {k: v for k, v in (route.get("traveller_coords") or {}).items()
              if not k.startswith("_")}
        keys = list(to) or list(tc)
        return [{"key": k, "name": k.title(),
                 "homes": [{"city": "", "lat": p[0], "lon": p[1]} for p in tc.get(k, [])],
                 "airports": list(to.get(k) or [])} for k in keys]

    @property
    def traveller_keys(self):
        return [t["key"] for t in self.travellers_norm]

    @property
    def traveller_names(self):
        return {t["key"]: t["name"] for t in self.travellers_norm}

    @property
    def traveller_cities(self):
        """Display label per traveller: 'London', 'Belfast / Dublin'."""
        return {t["key"]: " / ".join(h["city"] for h in t.get("homes", []) if h.get("city"))
                for t in self.travellers_norm}

    @property
    def origin(self):
        """Departure airports per traveller as the comma-joined string
        serp_flights expects."""
        return {t["key"]: ",".join(t.get("airports") or [])
                for t in self.travellers_norm}

    @property
    def origin_coords(self):
        """Home [lat, lon] points per traveller for the distance-from-home
        signal — the nearest is used."""
        return {t["key"]: [(h["lat"], h["lon"]) for h in t.get("homes", [])]
                for t in self.travellers_norm}

    @classmethod
    def from_files(cls, venues_cfg, flights_cfg, serpapi_key=None, top_n_flights=4):
        """Build a TripContext from parsed venues.json/flights.json content —
        the shape both the NI cron and future per-user Lambda trips share."""
        return cls(
            trip_name=venues_cfg["trip"],
            target_start=date.fromisoformat(venues_cfg["target_window"]["start"]),
            target_end=date.fromisoformat(venues_cfg["target_window"]["end"]),
            venues=venues_cfg["venues"],
            flights_cfg=flights_cfg,
            serpapi_key=serpapi_key,
            top_n_flights=top_n_flights,
        )
