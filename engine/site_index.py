"""Back-compat shim — this module now lives at `domains.climbing.site_index`.

Kept so existing imports (`engine.site_index`) keep resolving after the core/ + domains/
split. Replacing this module object with the real one means every name —
including private helpers like `_slug` — stays the same object, so there is no
list here to drift out of date.

New code should import `domains.climbing.site_index` directly.
"""
import sys

from domains.climbing import site_index as _real

sys.modules[__name__] = _real
