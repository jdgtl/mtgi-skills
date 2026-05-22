"""Workspace-folder detection for the rfq-normalizer skill.

Returns a directory that persists across Cowork sandbox resets, so the
skill can store credentials and cache files there.

Resolution order:
  1. $RFQ_WORKSPACE_DIR (explicit override)
  2. First writable path from _AUTODETECT_CANDIDATES (Cowork mounts)
  3. $HOME

Always returns a directory that exists and is writable.
"""
from __future__ import annotations
import os
from pathlib import Path

# Common persistent-mount paths in Cowork-style sandboxes, in priority order.
_AUTODETECT_CANDIDATES: tuple[Path, ...] = (
    Path("/mnt/user-data"),
    Path("/workspace"),
)


def _is_writable_dir(p: Path) -> bool:
    return p.is_dir() and os.access(p, os.W_OK)


def workspace_dir() -> Path:
    explicit = os.environ.get("RFQ_WORKSPACE_DIR")
    if explicit:
        p = Path(explicit)
        p.mkdir(parents=True, exist_ok=True)
        return p

    for candidate in _AUTODETECT_CANDIDATES:
        if _is_writable_dir(candidate):
            return candidate

    return Path.home()
