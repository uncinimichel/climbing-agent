"""Bbox helpers. Canonical bbox everywhere in this module: (south, west,
north, east) in decimal degrees — the same order the CLI takes
(`--bbox S,W,N,E`). Sources that speak other conventions (OpenBeta's
GeoJSON-style lnglat, theCrag's [[lat,lng],[lat,lng]] page blob) convert at
their own edge, never here."""
from __future__ import annotations

import math

Bbox = tuple[float, float, float, float]  # south, west, north, east


def parse_bbox(text: str) -> Bbox:
    parts = [float(p) for p in text.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be S,W,N,E (four comma-separated numbers)")
    s, w, n, e = parts
    if not (-90 <= s < n <= 90):
        raise ValueError(f"bbox latitudes wrong: south={s} north={n}")
    if not (-180 <= w < e <= 180):
        raise ValueError(f"bbox longitudes wrong: west={w} east={e} (antimeridian boxes unsupported)")
    return (s, w, n, e)


def contains(bbox: Bbox, lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    s, w, n, e = bbox
    return s <= lat <= n and w <= lon <= e


def intersects(a: Bbox, b: Bbox) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def center(bbox: Bbox) -> tuple[float, float]:
    s, w, n, e = bbox
    return ((s + n) / 2, (w + e) / 2)


def covering_radius_m(bbox: Bbox) -> int:
    """Distance from the bbox center to a corner — the radius a point+radius
    source (OpenBeta cragsNear) needs to cover the whole box."""
    clat, clon = center(bbox)
    s, w, n, e = bbox
    return int(math.ceil(_haversine_m(clat, clon, n, e)))


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
