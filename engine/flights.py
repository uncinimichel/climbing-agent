"""Back-compat shim — this module now lives at `core.travel.flights`.

Kept so existing imports (`engine.flights`) keep resolving after the core/ + domains/
split. Replacing this module object with the real one means every name —
including private helpers like `_slug` — stays the same object, so there is no
list here to drift out of date.

New code should import `core.travel.flights` directly.
"""
import sys

from core.travel import flights as _real

sys.modules[__name__] = _real
