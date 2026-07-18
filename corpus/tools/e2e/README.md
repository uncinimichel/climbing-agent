# Studio E2E + demo recorder

Playwright harness for the Curation Studio (localhost:8890, route 1051 =
the fictional "Granite Whisper" demo route).

- `e2e_topo.py` — ~20-check suite: card editing, ⌘⏎/partial-render
  regressions (17 Jul review P0s), rights-gated photo upload, the unified
  topo/pitch flow, persistence, dark mode. Run it before touching
  curate_ui.html or topo_api.py.
- `demo_video.py` — records the narrated demo (branded captions in the
  Studio's own design tokens, fake cursor, title/end cards) to
  `video/*.webm`; convert with ffmpeg for sharing.

Setup (once):
    python3 -m venv .venv && .venv/bin/pip install playwright && .venv/bin/playwright install chromium

Reset the demo route between runs (see the DELETE/UPDATE block in the repo
history or scratchpad) — both scripts assume a clean route 1051.
