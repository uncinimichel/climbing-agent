"""TripContext: the parameterized replacement for update_report.py's module-level
trip globals (TRIP_NAME, TARGET_START/END, FLIGHTS_CFG, ORIGIN, REP, ...).

Every value that used to be read from a module global at import time is now
either a field on TripContext (venues, flights_cfg, dates, serpapi_key) or a
derived property computed from those fields (graph window, rep combo, period
label) — so the same object can represent the one hardcoded NI trip today, or
an arbitrary user-defined trip tomorrow.

Traveller keys stay hardcoded to ("michel", "dan") for now, matching
venues.json's `travel` dicts and every downstream function that keys off them
(flights.py, render.py's PAGE_JS). Generalizing to an arbitrary traveller list
is out of scope for this refactor (zero functional change) — see M2+ in the
implementation plan.
"""
from dataclasses import dataclass, field
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


TRAVELLERS = ("michel", "dan")
ORIGIN_CITY = {"michel": "London", "dan": "Belfast/Dublin"}
# Home coordinates per traveller, for the distance-from-home signal. Each is a
# list (Dan can start from Belfast or Dublin) — the nearest is used.
ORIGIN_COORDS = {
    "michel": [(51.5074, -0.1278)],                       # London
    "dan": [(54.607, -5.926), (53.349, -6.260)],          # Belfast, Dublin
}
DEFAULT_CLIMO_YEARS = [2021, 2022, 2023, 2024]


@dataclass
class Preferences:
    """Per-sub-signal ranking preferences. Every field is a neutral 1.0 today
    (identical to the un-weighted mean) — this is the hook a future per-user
    preferences UI writes into. tol fields soften a penalty (>1 = more
    tolerant); the rest are relative weights within their component."""
    # weather penalties (>1 = more tolerant of that condition)
    heat_tol: float = 1.0
    rain_tol: float = 1.0
    # travel sub-signals
    cost: float = 1.0
    distance: float = 1.0
    # fit sub-signals
    volume: float = 1.0
    difficulty: float = 1.0
    trip_fit: float = 1.0
    coverage: float = 1.0
    fit_distance: float = 1.0
    # top-level component emphasis
    weather: float = 1.0
    travel: float = 1.0
    fit: float = 1.0


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
    prefs: Preferences = field(default_factory=Preferences)

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

    @property
    def origin(self):
        to = self.flights_cfg["route"].get("traveller_origins", {})
        return {
            "michel": ",".join(to.get("michel", self.flights_cfg["route"]["origin_airports"])),
            "dan": ",".join(to.get("dan", self.flights_cfg["route"]["dest_airports"])),
        }

    @property
    def origin_city(self):
        return dict(ORIGIN_CITY)

    @property
    def origin_coords(self):
        """Home [lat, lon] per traveller for the distance-from-home signal, read
        from flights.json's route.traveller_coords (falls back to ORIGIN_COORDS).
        Keys starting with '_' (e.g. a JSON _comment) are skipped."""
        tc = (self.flights_cfg.get("route") or {}).get("traveller_coords")
        src = tc if tc else ORIGIN_COORDS
        return {k: [tuple(p) for p in v]
                for k, v in src.items() if not k.startswith("_")}

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
