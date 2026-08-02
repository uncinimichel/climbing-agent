"""Where things live on disk.

Exists because `Path(__file__).parents[1]` is a landmine: it silently encodes
how deep the file currently sits, so moving a module one directory changes what
it points at — with no error, just wrong data. That is exactly what happened
when render.py moved into domains/climbing/ and quietly stopped finding the
chatter cache.

Anchor on this instead. It resolves from core/, which is a fixed depth under the
repo root, and everything else asks it.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CACHE_DIR = REPO_ROOT / "cache"
KNOWLEDGE_DIR = REPO_ROOT / "knowledge"
CORPUS_DIR = REPO_ROOT / "corpus"
TRIPS_DIR = REPO_ROOT / "trips"


def cache_file(name):
    """A file in the shared repo-root cache/ directory."""
    return CACHE_DIR / name
