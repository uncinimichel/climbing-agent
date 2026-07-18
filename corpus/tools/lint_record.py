#!/usr/bin/env python3
"""Validate the whole JSON record — the CI/pre-push gate (decision #39).

Every route re-validated against the taxonomy-generated schema + the
referential lint. Exit 1 with a readable list if anything is off: this is
the "database says no" moment, relocated to commit time.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from store import Store  # noqa: E402


def main() -> int:
    s = Store()
    problems = s.lint()
    print(f"record: {len(s.routes)} routes, {len(s.areas)} areas, "
          f"{len(s.topos)} topos, {sum(len(v) for v in s.tax.values())} taxonomy values")
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print("  ✗", p)
        return 1
    print("record valid ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
