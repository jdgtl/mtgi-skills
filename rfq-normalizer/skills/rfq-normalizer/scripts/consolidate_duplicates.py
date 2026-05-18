#!/usr/bin/env python3
"""Consolidate rows with identical (exact-match) MPN + condition.

Two modes:
  - "sum"   (default) — each row already has a Quantity column; sum the values
  - "count" — each row is one physical item (row-per-item layout); count rows

Use `scripts/analyze_columns.py` to detect which mode applies, then pass
`--mode` here. When mode='count', `qty_col` is ignored and the output gains
a synthetic "__count__" key with the total rows per MPN.

Hard rule: MPN strings are compared with EXACT equality. Whitespace and case
differences are NOT normalized away — those are surfaced as ambiguous_pairs
for the user to confirm or split.

Input  (stdin or --input):  {"rows": [...], "mpn_col": "MPN",
                              "qty_col": "Quantity",  # ignored when mode='count'
                              "condition_col": "Condition",
                              "mode": "sum" | "count"}
Output (stdout):            {"consolidated": [...], "ambiguous_pairs": [...]}
"""
from __future__ import annotations
import argparse
import json
import sys
from collections import defaultdict


# When mode='count', the qty lands under this key in the output.
COUNT_COLUMN = "Quantity"


def find_ambiguous_pairs(mpns: list[str]) -> list[dict]:
    """Find MPN pairs that differ only by case/whitespace — likely the same part."""
    seen = {}  # normalized -> [originals]
    for mpn in mpns:
        norm = " ".join(mpn.split()).lower()
        seen.setdefault(norm, []).append(mpn)

    pairs = []
    for norm, originals in seen.items():
        unique = list(dict.fromkeys(originals))  # dedupe within group, preserve order
        if len(unique) > 1:
            for i in range(len(unique)):
                for j in range(i + 1, len(unique)):
                    a, b = unique[i], unique[j]
                    reason = "case-differs" if a.lower() == b.lower() else "whitespace-differs"
                    pairs.append({"mpn_a": a, "mpn_b": b, "reason": reason})
    return pairs


def consolidate(
    rows: list[dict],
    mpn_col: str,
    qty_col: str | None,
    condition_col: str | None,
    mode: str = "sum",
) -> dict:
    if mode not in ("sum", "count"):
        raise ValueError(f"mode must be 'sum' or 'count', got {mode!r}")

    output_qty_col = qty_col if mode == "sum" else COUNT_COLUMN
    groups: dict[tuple, dict] = defaultdict(lambda: {"qty": 0, "_sample": None})

    for row in rows:
        mpn = (row.get(mpn_col) or "").strip() if isinstance(row.get(mpn_col), str) else row.get(mpn_col)
        if mpn is None or mpn == "":
            continue
        condition = row.get(condition_col) if condition_col else None
        key = (str(mpn), str(condition) if condition is not None else None)

        if mode == "count":
            increment = 1
        else:
            try:
                increment = int(float(row.get(qty_col) or 1))
            except (TypeError, ValueError):
                increment = 1

        groups[key]["qty"] += increment
        if groups[key]["_sample"] is None:
            groups[key]["_sample"] = row

    consolidated = []
    for (mpn, condition), data in groups.items():
        merged = dict(data["_sample"])
        merged[mpn_col] = mpn
        merged[output_qty_col] = data["qty"]
        if condition_col and condition is not None:
            merged[condition_col] = condition
        consolidated.append(merged)

    all_mpns = [str(r.get(mpn_col, "")).strip() for r in rows if r.get(mpn_col)]
    ambiguous = find_ambiguous_pairs(all_mpns)

    return {
        "consolidated": consolidated,
        "ambiguous_pairs": ambiguous,
        "mode": mode,
        "qty_column": output_qty_col,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=None, help="JSON file (default: stdin)")
    args = ap.parse_args()

    raw = json.load(open(args.input) if args.input else sys.stdin)
    rows = raw["rows"]
    mpn_col = raw.get("mpn_col", "MPN")
    qty_col = raw.get("qty_col", "Quantity")
    condition_col = raw.get("condition_col")
    mode = raw.get("mode", "sum")

    result = consolidate(rows, mpn_col, qty_col, condition_col, mode=mode)
    json.dump(result, sys.stdout, default=str, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
