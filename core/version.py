"""Project version helpers."""

from __future__ import annotations

from pathlib import Path


def get_version() -> str:
    """Return the release version from the repository VERSION file."""
    version_file = Path(__file__).resolve().parent.parent / "VERSION"
    return version_file.read_text(encoding="utf-8").strip()


__version__ = get_version()
