"""Cache protocol used by weather.py/stays.py, plus a DiskCache implementation
that matches today's *-cache.json behavior exactly (load whole file once, keep
in memory, rewrite the whole file on every update) — used by the cron driver.

A DynamoCache implementation (per the plan's milestone M2/M3, backed by
ClimbingAgentFlightCache-style tables so weather/stays caching is shared across
every user's trips) is a later milestone, not part of this zero-behavior-change
refactor — DiskCache is the only implementation needed to keep the NI cron
working exactly as it does today.
"""
import json


class Cache:
    """get/set protocol. Any object with this shape works with weather.py/stays.py."""

    def get(self, key, default=None):
        raise NotImplementedError

    def set(self, key, value):
        raise NotImplementedError


class DiskCache(Cache):
    """Loads `path` as a JSON object at construction, serves gets from memory,
    and rewrites the whole file on every set() — same persistence pattern as
    today's climo-cache.json/stays-cache.json/link-health-cache.json. Failure to
    read or write is swallowed (a fresh/uncommitted cache file, or a read-only
    filesystem, must never fail the build — it just re-fetches live)."""

    def __init__(self, path, key_filter=None):
        self._path = path
        try:
            data = json.loads(path.read_text())
        except Exception:
            data = {}
        self._data = {k: v for k, v in data.items() if key_filter is None or key_filter(k)}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        try:
            self._path.write_text(json.dumps(self._data))
        except Exception:
            pass

    def items(self):
        return dict(self._data)


class EnvCache:
    """Read-only wrapper around venue-env.json (decision #24) — fetch_env.py
    writes the trip-independent weather/tide layer once per venue; this just
    serves it back by "lat,lon" so the live fetchers can skip re-hitting the
    provider APIs. Missing file/venue is not an error — callers fall back to a
    live call, exactly as today."""

    def __init__(self, path):
        try:
            env = json.loads(path.read_text())
            self._by_coord = {f"{x['lat']},{x['lon']}": x for x in env.get("venues", {}).values()}
        except Exception:
            self._by_coord = {}

    def raw(self, lat, lon, key):
        hit = self._by_coord.get(f"{lat},{lon}")
        return (hit.get("raw") or {}).get(key) if hit else None

    def __len__(self):
        return len(self._by_coord)
