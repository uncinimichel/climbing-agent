"""Climbing's ranking knobs — the hook a per-user preferences UI writes into.

Every field is a neutral 1.0, which is exactly what core's NeutralPreferences
already gives you, so nothing constructs this yet. It exists to name the knobs
climbing actually has: tolerances soften a penalty (>1 = more tolerant), the
rest are relative weights within their component.
"""
from dataclasses import dataclass


@dataclass
class ClimbingPreferences:
    # weather penalties (>1 = more tolerant of that condition)
    heat_tol: float = 1.0
    rain_tol: float = 1.0
    # travel sub-signals
    cost: float = 1.0
    distance: float = 1.0
    # fit sub-signals — the curated sheet's judgement columns
    volume: float = 1.0
    difficulty: float = 1.0
    trip_fit: float = 1.0
    coverage: float = 1.0
    fit_distance: float = 1.0
    # top-level component emphasis
    weather: float = 1.0
    travel: float = 1.0
    fit: float = 1.0
