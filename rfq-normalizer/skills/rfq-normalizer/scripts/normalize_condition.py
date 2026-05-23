#!/usr/bin/env python3
"""Vendor condition string → MTGI condition enum.

A single entry point that handles the three ways vendors express condition:

  1. Bare grade letters/numbers ("B", "A+", "3")        → via normalize_grade
  2. Grade words with a "grade" token ("B grade",        → strip token, then
     "Grade B")                                            normalize_grade
  3. Plain condition words ("Good", "Refurb", "Pull")    → word-variant map

Never guesses: unrecognized input returns None so the caller can leave the
Condition cell blank (the MTGI wizard treats blank as `unknown`). Condition
has warranty/legal implications — see reference/condition-mapping.md.
"""
from __future__ import annotations

import re

from normalize_grade import normalize_grade

# MTGI canonical condition enum values.
_NEW         = "new"
_REFURBISHED = "refurbished"
_LIKE_NEW    = "used_like_new"
_GOOD        = "used_good"
_FAIR        = "used_fair"
_FOR_PARTS   = "for_parts"

# Word variants → canonical enum (mirrors reference/condition-mapping.md).
# Keys are lowercased and whitespace-collapsed.
_WORD_MAP: dict[str, str] = {
    "new": _NEW, "new sealed": _NEW, "sealed": _NEW,
    "refurb": _REFURBISHED, "refurbished": _REFURBISHED,
    "recertified": _REFURBISHED, "cpo": _REFURBISHED,
    "used-a": _LIKE_NEW, "used a": _LIKE_NEW, "used like new": _LIKE_NEW,
    "used": _GOOD, "pull": _GOOD, "server pull": _GOOD, "used good": _GOOD,
    "good": _GOOD,  # v0.7: vendors use bare "Good" for tested-working drives
    "used fair": _FAIR,
    "broken": _FOR_PARTS, "defective": _FOR_PARTS,
    "for parts": _FOR_PARTS, "for_parts": _FOR_PARTS,
}

# Strips a leading or trailing "grade" token: "B grade" / "Grade B" → "B".
_GRADE_TOKEN_RE = re.compile(r"^\s*grade\s+|\s+grade\s*$", re.I)


def normalize_condition(raw: str | None) -> str | None:
    """Return the MTGI canonical condition for a vendor condition/grade string,
    or None when it can't be confidently determined (never guess)."""
    if not raw or not isinstance(raw, str):
        return None

    collapsed = " ".join(raw.strip().split())
    if not collapsed:
        return None

    # 1 & 2: strip a "grade" token, then try the letter/number grade map.
    degraded = _GRADE_TOKEN_RE.sub("", collapsed).strip()
    graded = normalize_grade(degraded)
    if graded:
        return graded

    # 3: fall back to the condition-word map.
    return _WORD_MAP.get(collapsed.lower())


if __name__ == "__main__":
    cases = [
        ("B grade", "used_good"), ("Grade B", "used_good"),
        ("A+", "used_like_new"), ("Good", "used_good"),
        ("refurb", "refurbished"), ("for parts", "for_parts"),
        ("xyz", None), ("", None), (None, None),
    ]
    for inp, expected in cases:
        got = normalize_condition(inp)
        ok = "✓" if got == expected else "✗"
        print(f"  {ok}  normalize_condition({inp!r:10}) = {got!s:15} (expected {expected!s})")
