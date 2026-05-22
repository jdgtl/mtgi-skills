#!/usr/bin/env python3
"""Persistent MPN enrichment cache.

Stores enrichment results keyed by uppercased MPN. Shared across all RFQs
imported by the team — a cache hit returns instantly with no API call,
preserving the BrokerBin quota.

Cache location (in priority order):
  1. $RFQ_CACHE_DIR env var (explicit override)
  2. <workspace_dir>/.rfq-cache/  (workspace.workspace_dir())
  3. $HOME/.cache/rfq-normalizer/  (last-resort fallback)

The skill folder is NEVER used — it's read-only in Cowork.

TTLs:
  - successful enrichment: CACHE_TTL_DAYS (default 60d — specs are stable)
  - "no listings" miss:    CACHE_MISS_TTL_DAYS (default 7d — vendor may list later)
  - errors:                not cached (assumed transient)

The cache is a single JSON file. For 10k MPNs that's ~5MB on disk — fine.
If it ever grows past that, swap for SQLite.
"""
from __future__ import annotations
import fcntl
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

CACHE_FILENAME = "brokerbin-enrichment.json"
CACHE_TTL_DAYS = 60
CACHE_MISS_TTL_DAYS = 7


def _cache_dir() -> Path:
    explicit = os.environ.get("RFQ_CACHE_DIR")
    if explicit:
        p = Path(explicit)
    else:
        try:
            from workspace import workspace_dir
            p = workspace_dir() / ".rfq-cache"
        except Exception:
            p = Path.home() / ".cache" / "rfq-normalizer"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _cache_path() -> Path:
    return _cache_dir() / CACHE_FILENAME


@contextmanager
def _cache_lock():
    """Exclusive lock over the cache dir, so concurrent put() calls serialize."""
    lock_path = _cache_dir() / ".lock"
    # touch the lockfile
    with open(lock_path, "a+") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _normalize_key(mpn: str) -> str:
    return mpn.strip().upper()


def _load_all() -> dict[str, Any]:
    path = _cache_path()
    if not path.exists():
        return {}
    try:
        with path.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_all(data: dict[str, Any]) -> None:
    path = _cache_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, indent=2, default=str)
    tmp.replace(path)  # atomic on POSIX


def _is_fresh(entry: dict, ttl_days: int) -> bool:
    cached_at = entry.get("cached_at")
    if not cached_at:
        return False
    try:
        dt = datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return datetime.now(timezone.utc) - dt < timedelta(days=ttl_days)


def get(mpn: str) -> dict | None:
    """Return cached enrichment for an MPN, or None if missing/stale."""
    data = _load_all()
    entry = data.get(_normalize_key(mpn))
    if not entry:
        return None
    ttl = CACHE_MISS_TTL_DAYS if entry.get("is_miss") else CACHE_TTL_DAYS
    if not _is_fresh(entry, ttl):
        return None
    return entry


def put(
    mpn: str,
    fields: dict,
    field_confidence: dict,
    source: str,
    is_miss: bool = False,
    extras: dict | None = None,
) -> None:
    """Store enrichment result. Pass is_miss=True for empty/no-listings results.

    `extras` is an optional free-form dict for tier-specific data that doesn't
    fit the flat fields/field_confidence shape — e.g. web_search's
    candidate_real_mpn. Old cache entries without `extras` read as {}.

    Parallel-safe: serialized via an fcntl lock on the cache dir.
    """
    entry = {
        "cached_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": source,
        "fields": fields,
        "field_confidence": field_confidence,
        "is_miss": is_miss,
    }
    if extras:
        entry["extras"] = extras
    with _cache_lock():
        data = _load_all()
        data[_normalize_key(mpn)] = entry
        _save_all(data)


def stats() -> dict:
    """Return cache statistics — useful for /scripts/check_setup.py output."""
    data = _load_all()
    now = datetime.now(timezone.utc)
    fresh_hit = 0
    fresh_miss = 0
    stale = 0
    for entry in data.values():
        ttl = CACHE_MISS_TTL_DAYS if entry.get("is_miss") else CACHE_TTL_DAYS
        if _is_fresh(entry, ttl):
            if entry.get("is_miss"):
                fresh_miss += 1
            else:
                fresh_hit += 1
        else:
            stale += 1
    return {
        "path": str(_cache_path()),
        "total_entries": len(data),
        "fresh_hits": fresh_hit,
        "fresh_misses": fresh_miss,
        "stale": stale,
    }


def clear(mpn: str | None = None) -> int:
    """Clear a specific MPN or the whole cache. Returns count removed."""
    if mpn is None:
        data = _load_all()
        n = len(data)
        _save_all({})
        return n
    data = _load_all()
    if _normalize_key(mpn) in data:
        del data[_normalize_key(mpn)]
        _save_all(data)
        return 1
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Cache utility commands")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("stats", help="Show cache statistics")
    p_clear = sub.add_parser("clear", help="Clear cache (or a specific MPN)")
    p_clear.add_argument("--mpn", default=None)
    p_show = sub.add_parser("show", help="Show cached entry for an MPN")
    p_show.add_argument("mpn")
    args = ap.parse_args()

    if args.cmd == "stats":
        print(json.dumps(stats(), indent=2))
    elif args.cmd == "clear":
        n = clear(args.mpn)
        print(f"Cleared {n} entries")
    elif args.cmd == "show":
        entry = get(args.mpn)
        if entry is None:
            print("(no fresh cache entry)")
        else:
            print(json.dumps(entry, indent=2))
    else:
        ap.print_help()
