"""Workspace-folder detection for the rfq-normalizer skill.

Returns a directory that persists across Cowork sandbox resets, so the
skill can store credentials and cache files there.

Resolution order:
  1. $RFQ_WORKSPACE_DIR                       (explicit override)
  2. Glob _SESSIONS_GLOB_ROOT/*/mnt/* for writable, non-system dirs
     (the Cowork desktop sandbox path); prefer ones with prior state.
  3. First writable path from _AUTODETECT_CANDIDATES                (legacy)
  4. $HOME

Always returns a directory that exists and is writable.
"""
from __future__ import annotations
import os
from pathlib import Path

# Static candidates for sandbox layouts that mount a workspace at a stable
# path (Cowork web, legacy Cowork builds, some CI runners).
_AUTODETECT_CANDIDATES: tuple[Path, ...] = (
    Path("/mnt/user-data"),
    Path("/workspace"),
)

# Cowork desktop puts the persistent workspace under /sessions/<id>/mnt/<dir>.
# Module-level so tests can monkeypatch it onto a tmp tree.
_SESSIONS_GLOB_ROOT: Path = Path("/sessions")

# Basenames under /sessions/*/mnt/* that are never the workspace.
_SESSIONS_EXCLUDED_NAMES: frozenset[str] = frozenset({"outputs", "uploads"})


def _is_writable_dir(p: Path) -> bool:
    return p.is_dir() and os.access(p, os.W_OK)


def _has_prior_state(p: Path) -> bool:
    """A workspace dir that already has our env file or cache is the one to pick."""
    return (p / ".rfq-normalizer.env").exists() or (p / ".rfq-cache").is_dir()


def _scan_sessions() -> Path | None:
    """Find a Cowork-style /sessions/<id>/mnt/<workspace> directory.

    Filters out non-workspace siblings (outputs, uploads, dotdirs) and prefers
    directories already containing our state files. Returns None if no
    candidate matches.
    """
    if not _SESSIONS_GLOB_ROOT.is_dir():
        return None
    candidates: list[Path] = []
    for p in sorted(_SESSIONS_GLOB_ROOT.glob("*/mnt/*")):
        name = p.name
        if name.startswith(".") or name in _SESSIONS_EXCLUDED_NAMES:
            continue
        if not _is_writable_dir(p):
            continue
        candidates.append(p)
    if not candidates:
        return None
    for c in candidates:
        if _has_prior_state(c):
            return c
    return candidates[0]


def workspace_dir() -> Path:
    explicit = os.environ.get("RFQ_WORKSPACE_DIR")
    if explicit:
        p = Path(explicit)
        p.mkdir(parents=True, exist_ok=True)
        return p

    sessions = _scan_sessions()
    if sessions is not None:
        return sessions

    for candidate in _AUTODETECT_CANDIDATES:
        if _is_writable_dir(candidate):
            return candidate

    return Path.home()
