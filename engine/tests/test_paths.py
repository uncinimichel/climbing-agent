"""Guards the failure mode the core/ + domains/ split introduced.

`render.py` located the chatter cache with `Path(__file__).parents[1]`. That was
correct while it sat in engine/, and silently wrong the moment it moved one level
deeper into domains/climbing/ — it resolved to `domains/cache/`, which does not
exist, so every venue's chatter quietly became null. Nothing raised; the page
just lost a column of data.

These tests fail loudly if that happens again, to any module.
"""
import json
import unittest
from pathlib import Path

from core import paths


class RepoRoot(unittest.TestCase):
    def test_repo_root_is_the_repo_root(self):
        """Anchored by a file that only exists at the top level."""
        self.assertTrue((paths.REPO_ROOT / "trips.json").is_file(),
                        f"REPO_ROOT resolved to {paths.REPO_ROOT}, which has no trips.json")
        self.assertTrue((paths.REPO_ROOT / "core").is_dir())
        self.assertTrue((paths.REPO_ROOT / "domains").is_dir())

    def test_cache_dir_exists_and_is_shared(self):
        self.assertTrue(paths.CACHE_DIR.is_dir(), f"{paths.CACHE_DIR} is not a directory")
        self.assertEqual(paths.cache_file("x.json").parent, paths.CACHE_DIR)


class ChatterCacheReachable(unittest.TestCase):
    """The specific regression: the renderer must actually find the chatter."""

    def test_renderer_loads_a_non_empty_chatter_cache(self):
        f = paths.cache_file("crag-chatter.json")
        if not f.is_file():
            self.skipTest("crag-chatter.json not present in this checkout")
        venues = (json.loads(f.read_text()).get("venues") or {})
        if not venues:
            self.skipTest("chatter cache is empty in this checkout")

        from domains.climbing import render
        render._CHATTER = None          # force a fresh load through the real path
        try:
            hits = sum(1 for name in venues if render._chatter_for(name))
        finally:
            render._CHATTER = None
        self.assertGreater(hits, 0,
                           "renderer found chatter for 0 of "
                           f"{len(venues)} cached venues — the cache path is wrong")


class NoFragilePathDepth(unittest.TestCase):
    """`parents[N]` encodes how deep a file currently sits. Moving the file then
    changes what it points at, with no error — so core/paths.py owns it instead."""

    def test_no_module_reaches_for_the_repo_root_by_depth(self):
        offenders = []
        for pkg in ("core", "domains"):
            for py in sorted((paths.REPO_ROOT / pkg).rglob("*.py")):
                if py == paths.REPO_ROOT / "core" / "paths.py":
                    continue          # the one place allowed to do this
                src = py.read_text()
                if "parents[" in src:
                    offenders.append(str(py.relative_to(paths.REPO_ROOT)))
        self.assertEqual(offenders, [],
                         "these modules resolve paths by directory depth; import "
                         "core.paths instead: " + ", ".join(offenders))


if __name__ == "__main__":
    unittest.main()
