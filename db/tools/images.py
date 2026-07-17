"""Image handling for Studio uploads (tech review, 17 Jul 2026): Pillow-based —
one pip wheel that works the same on this Mac, GitHub Actions and Lambda,
replacing the earlier sips/ffmpeg shell-outs (whose two paths disagreed on
EXIF orientation and max dimensions).

Two jobs:

  normalize(original)      bake EXIF orientation INTO the pixels and strip the
                           tag, so every consumer — browser, canvas editor,
                           future booklet renderer — sees one unambiguous
                           coordinate space. Returns (width, height) of the
                           oriented image. Topo coordinates are stored as 0-1
                           fractions of exactly this space.

  derive(original)         WebP variants next to the original (~97% browser
                           support; measurably smaller than JPEG at q80):
                               <stem>-thumb.webp   360px  — list thumbnails
                               <stem>-web.webp    1600px  — page display
                           Idempotent, best-effort: failure never blocks an
                           upload (UI falls back onerror → original). AVIF is
                           a later, export-time upgrade (Pillow ≥11.3 has it).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

SIZES = {"thumb": 360, "web": 1600}
Image.MAX_IMAGE_PIXELS = 120_000_000   # 8-10MP phone panoramas are fine; bombs are not


def variant_paths(original: Path) -> dict[str, Path]:
    return {k: original.with_name(f"{original.stem}-{k}.webp") for k in SIZES}


def normalize(original: Path) -> tuple[int, int]:
    """Bake EXIF orientation into the pixels (no-op when already upright);
    returns the oriented (width, height) — the topo coordinate space."""
    with Image.open(original) as im:
        oriented = ImageOps.exif_transpose(im)
        if oriented is not im:                     # had a rotation to bake
            oriented.save(original, quality=92)
        return oriented.size


def derive(original: Path) -> dict[str, str]:
    """Create missing/stale variants; returns {kind: filename} of what exists."""
    out: dict[str, str] = {}
    for kind, px in SIZES.items():
        dest = variant_paths(original)[kind]
        try:
            if not dest.exists() or dest.stat().st_mtime < original.stat().st_mtime:
                with Image.open(original) as im:
                    v = ImageOps.exif_transpose(im)
                    v.thumbnail((px, px), Image.LANCZOS)
                    v.save(dest, "WEBP", quality=80)
            out[kind] = dest.name
        except Exception:
            dest.unlink(missing_ok=True)   # never leave a half-written variant
    return out


def derive_tree(root: Path) -> int:
    """Backfill variants for every original under root (skips derived files)."""
    n = 0
    for p in sorted(root.rglob("*")):
        if (p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
                and not any(p.stem.endswith(f"-{k}") for k in SIZES)):
            if derive(p):
                n += 1
    return n


if __name__ == "__main__":
    import sys
    root = Path(sys.argv[1] if len(sys.argv) > 1 else
                Path(__file__).resolve().parents[1] / "uploads" / "topos")
    print(f"derived variants for {derive_tree(root)} originals under {root}")
