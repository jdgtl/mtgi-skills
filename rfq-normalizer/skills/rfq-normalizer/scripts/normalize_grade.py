#!/usr/bin/env python3
"""Grade letter → MTGI condition enum.

Many vendor inventory lists (drive lots especially) use a single-letter
grade column instead of a full condition word. Translate to MTGI's enum.

Convention used in IT-equipment refurb industry:
  A+   — flawless, no marks (new-equivalent)
  A    — minor cosmetic, fully functional   → used_like_new
  B+   — light wear, tested working          → used_good (high end)
  B    — moderate wear, tested working       → used_good
  C+   — heavy cosmetic, tested working      → used_fair (high end)
  C    — heavy cosmetic, may have soft errors → used_fair
  D    — non-working but salvageable         → for_parts
  F    — scrap                                → for_parts

Some vendors use numeric grades (1–5) which we treat similarly.

This module is INTENTIONALLY separate from condition-mapping.md — grade
letters are an MTGI-specific convention that won't appear in BrokerBin
API responses. Keep them out of the BrokerBin mapper to avoid pollution.
"""
from __future__ import annotations

# MTGI canonical condition enum values
_NEW          = "new"
_REFURBISHED  = "refurbished"
_LIKE_NEW     = "used_like_new"
_GOOD         = "used_good"
_FAIR         = "used_fair"
_FOR_PARTS    = "for_parts"

# Letter-grade → condition. Keys are lowercased.
_GRADE_MAP: dict[str, str] = {
    # Highest tier
    "a+":  _LIKE_NEW,
    "a":   _LIKE_NEW,
    "1":   _LIKE_NEW,
    "1+":  _LIKE_NEW,
    # Good
    "b+":  _GOOD,
    "b":   _GOOD,
    "2":   _GOOD,
    "2+":  _GOOD,
    # Fair
    "c+":  _FAIR,
    "c":   _FAIR,
    "3":   _FAIR,
    "3+":  _FAIR,
    # For parts / scrap
    "d":   _FOR_PARTS,
    "d-":  _FOR_PARTS,
    "f":   _FOR_PARTS,
    "4":   _FOR_PARTS,
    "5":   _FOR_PARTS,
}


def normalize_grade(raw: str | None) -> str | None:
    """Return MTGI canonical condition for a single-letter or numeric grade.

    Returns None for unrecognized input (don't guess — let the caller decide
    whether to ask the user or fall back to another column).
    """
    if not raw or not isinstance(raw, str):
        return None
    key = raw.strip().lower()
    return _GRADE_MAP.get(key)


if __name__ == "__main__":
    test_cases = [
        ("A+", "used_like_new"),
        ("A",  "used_like_new"),
        ("B+", "used_good"),
        ("B",  "used_good"),
        ("C",  "used_fair"),
        ("c",  "used_fair"),
        (" B ", "used_good"),
        ("D",  "for_parts"),
        ("F",  "for_parts"),
        ("3",  "used_fair"),
        ("Z",  None),
        ("",   None),
        (None, None),
    ]
    for inp, expected in test_cases:
        got = normalize_grade(inp)
        ok = "✓" if got == expected else "✗"
        print(f"  {ok}  normalize_grade({inp!r:8}) = {got!s:15} (expected {expected!s})")
