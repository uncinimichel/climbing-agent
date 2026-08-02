"""Which weather icons the climbing dashboard draws with.

A leaf module on purpose: the scorer and the renderer both need `wmo_icon`, and
routing that through render.py made the scorer import 2,300 lines of HTML.
"""
from core.weather.codes import WMO, icon_name  # noqa: F401 — re-exported

from .climbs import SITE_URL

MP_ICONS = SITE_URL + "img/icons/weather/"


def wmo_icon(code):
    """WMO weather code -> multi-pitch.com icon URL (day variants)."""
    name = icon_name(code)
    return None if name is None else MP_ICONS + name + ".svg"
