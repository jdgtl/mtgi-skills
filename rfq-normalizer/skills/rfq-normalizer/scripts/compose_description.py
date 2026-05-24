#!/usr/bin/env python3
"""Compose a fallback Description from confirmed canonical spec fields (v0.9.3).

The MTGI template's `Description` is an optional free-text fallback. When a row
has no human-written vendor description, this builds a readable spec summary
from the *already-resolved, already-cited* canonical columns — e.g.
`"Western Digital 6TB HDD SATA 3.5in"`.

This does not violate the never-invent rule: it only concatenates fields that
were filled and sourced upstream, and it is **fill-blank-only** — a real vendor
description is never overwritten, and the `(vendor MPN: …)` audit tag added in
step 2b is always preserved. Composed values are marked `source: composed` in
provenance so they're distinguishable from sourced spec values.

    echo '{"rows":[{...canonical columns...}]}' | python compose_description.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

# Canonical columns combined into the summary, in reading order.
FIELD_ORDER = ["Manufacturer", "Capacity", "Drive Type", "Interface", "Form Factor"]
MIN_FIELDS = 2  # too few confirmed fields → not worth composing

# The audit tag appended in SKILL step 2b, e.g. "(vendor MPN: ST6000NM0004)".
_AUDIT_RE = re.compile(r"\s*\(vendor MPN:[^)]*\)\s*$")


def _clean(v: Any) -> str:
    return str(v).strip() if v is not None and str(v).strip() else ""


def compose_description(values: dict[str, Any]) -> str:
    """Build a spec summary from canonical field values. Returns "" when fewer
    than MIN_FIELDS of the core fields are present (never guess from too little)."""
    parts = [_clean(values.get(k)) for k in FIELD_ORDER]
    parts = [p for p in parts if p]
    if len(parts) < MIN_FIELDS:
        return ""
    speed = _clean(values.get("Speed"))
    if speed:
        parts.append(f"{speed} RPM")
    return " ".join(parts)


def fill_description(row: dict[str, Any]) -> dict[str, Any]:
    """Fill a row's Description from its specs when it has no human text.

    Fill-blank-only: an existing vendor description is left untouched. The
    `(vendor MPN: …)` audit tag is split off, preserved, and re-appended.
    """
    desc = row.get("Description") or ""
    m = _AUDIT_RE.search(desc)
    audit = m.group(0).strip() if m else ""
    human = _AUDIT_RE.sub("", desc).strip()

    if not human:
        composed = compose_description(row)
        if composed:
            human = composed
            prov = row.setdefault("_provenance", {})
            prov["Description"] = {
                "source": "composed",
                "confidence": 1.0,
                "derived_from": [k for k in FIELD_ORDER if _clean(row.get(k))],
            }

    combined = f"{human} {audit}".strip() if audit else human
    row["Description"] = combined or None
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default=None, help="JSON file (default: stdin)")
    args = ap.parse_args()
    raw = json.load(open(args.input) if args.input else sys.stdin)
    if isinstance(raw, dict) and "rows" in raw:
        out: Any = {"rows": [fill_description(r) for r in raw["rows"]]}
    elif isinstance(raw, list):
        out = [fill_description(r) for r in raw]
    else:
        out = fill_description(raw)
    json.dump(out, sys.stdout, default=str, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
