"""Guards the "a venue is never placed by guesswork" rule.

The spreadsheet names areas in its own spelling. Those names used to fall
through to a free geocoder whenever the trip did not curate a matching name,
and the geocoder is confident and wrong:

    Aaran, Scotland        -> ‘Arān, Aleppo Governorate, Syria   (ranked 13th on
                              Aleppo's December weather, 14°C, above the real Arran)
    Mournes, N. Ireland    -> Crete, Greece
    Lake District, England -> San Francisco, USA
    Cornwall, England      -> Pennsylvania, USA  (which pushed a genuinely good
                              winter sea-cliff venue down to 60th)

Nothing failed. The venues rendered, scored and ranked — just on another
continent's weather. That is the failure mode these tests exist to prevent.
"""
import unittest
from pathlib import Path

from core.paths import REPO_ROOT
from domains.climbing import venues as V

# Rough bounding boxes: (lat_min, lat_max, lon_min, lon_max)
COUNTRY_BOX = {
    "scotland": (54.6, 61.0, -8.7, -0.7),
    "n. ireland": (54.0, 55.3, -8.2, -5.4),
    "england": (49.9, 55.8, -6.5, 1.8),
    "wales": (51.3, 53.5, -5.4, -2.6),
    "austria": (46.3, 49.1, 9.5, 17.2),
    "italy": (36.6, 47.1, 6.6, 18.6),
    "spain": (35.9, 43.8, -9.4, 4.4),
}


class SheetAreasArePlacedByHand(unittest.TestCase):
    """Every area the sheet names must resolve to curated coordinates."""

    def setUp(self):
        cfg = Path(REPO_ROOT / "trips" / "winter-trip-a" / "venues.json")
        import json
        self.curated = json.loads(cfg.read_text())["venues"]
        self.built = V.build_venues(self.curated, REPO_ROOT / "climbing-trips.csv")

    def test_previously_misplaced_areas_are_in_the_right_country(self):
        by_name = {v["name"]: v for v in self.built}
        for name in ("Aaran", "Mournes", "Lake District", "Cornwall", "Llanberis",
                     "East Tyrol", "Picos Europa", "Dolomites"):
            with self.subTest(venue=name):
                v = by_name.get(name)
                self.assertIsNotNone(v, f"{name} vanished from the merged venue list")
                box = COUNTRY_BOX.get((v.get("country") or "").strip().lower())
                if box is None:
                    continue
                la_lo, la_hi, lo_lo, lo_hi = box
                self.assertTrue(
                    la_lo <= v["lat"] <= la_hi and lo_lo <= v["lon"] <= lo_hi,
                    f"{name} says {v['country']} but sits at "
                    f"{v['lat']:.2f},{v['lon']:.2f} — outside that country")

    def test_every_built_venue_has_coordinates(self):
        for v in self.built:
            with self.subTest(venue=v["name"]):
                self.assertIsNotNone(v.get("lat"))
                self.assertIsNotNone(v.get("lon"))


class NeverGuessACoordinate(unittest.TestCase):
    def test_unknown_sheet_row_is_skipped_not_geocoded(self):
        """A row with no GAZETTEER entry must be dropped, not looked up."""
        calls = []
        real = V.geocode_suggestions
        V.geocode_suggestions = lambda name, count=3: (calls.append(name) or [])
        try:
            csv = REPO_ROOT / "climbing-trips.csv"
            built = V.build_venues([], csv)
        finally:
            V.geocode_suggestions = real
        names = {v["name"] for v in built}
        # whatever it suggested for, it must not have USED it
        for n in calls:
            self.assertNotIn(n, names,
                             f"'{n}' had no curated coords yet still got ranked")

    def test_no_module_calls_a_geocoder_for_coordinates(self):
        src = (REPO_ROOT / "domains" / "climbing" / "venues.py").read_text()
        self.assertNotIn("or geocode(", src,
                         "build_venues is guessing coordinates again")
        # the aid is allowed; silently trusting it is not
        self.assertIn("geocode_suggestions", src)


if __name__ == "__main__":
    unittest.main()
