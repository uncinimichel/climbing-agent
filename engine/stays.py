"""Back-compat shim — this module now lives at `core.travel.stays`.

Kept so existing imports (`engine.stays`) keep resolving after the core/ + domains/
split. Replacing this module object with the real one means every name —
including private helpers like `_slug` — stays the same object, so there is no
list here to drift out of date.

New code should import `core.travel.stays` directly.
"""
import sys

from core.travel import stays as _real

sys.modules[__name__] = _real
