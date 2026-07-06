"""Trip-computation engine: parameterized weather/flights/stays/scoring/render
logic extracted from trip-ni-july-2026/scripts/update_report.py so it can run
against ANY TripContext, not just the one hardcoded NI trip.

Every function here takes its trip-specific inputs as parameters (a TripContext,
or plain lat/lon/dates) instead of reading module-level globals — that's the
whole point of this package (see knowledge/roadmap/decisions.md #25).
"""
