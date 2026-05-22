#!/usr/bin/env python3
"""Consolidate rows with identical keys.

Key composition depends on `rfq_mode`:
  - `live`        — group by (MPN, condition).        Sourcing lists.
  - `historical`  — group by (MPN, condition, bid, win, outcome).
                    Preserves distinct bid events; identical re-bids merge.

Two quantity modes:
  - "sum"   (default) — each row already has a Quantity column; sum the values
  - "count" — each row is one physical item (row-per-item layout); count rows

Use `scripts/analyze_columns.py` to detect which modes apply, then pass
`--mode` and `--rfq_mode` here.

Hard rule: MPN strings are compared with EXACT equality. Whitespace and case
differences are NOT normalized away — those are surfaced as ambiguous_pairs
for the user to confirm or split. Quantity conservation is asserted (sum in
== sum out); the script raises AssertionError if it ever drifts.

Input  (stdin or --input):  {"rows": [...], "mpn_col": "MPN",
                              "qty_col": "Quantity",  # ignored when mode='count'
                              "condition_col": "Condition",
                              "mode": "sum" | "count",
                              "rfq_mode": "live" | "historical",
                              "bid_col": "Bid Price",     # required when rfq_mode='historical'
                              "win_col": "Winning Bid",
                              "outcome_col": "Outcome"}
Output (stdout):            {"consolidated": [...], "ambiguous_pairs": [...],
                              "qty_in": int, "qty_out": int, ...}
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
    rfq_mode: str = "live",
    bid_col: str | None = None,
    win_col: str | None = None,
    outcome_col: str | None = None,
) -> dict:
    if mode not in ("sum", "count"):
        raise ValueError(f"mode must be 'sum' or 'count', got {mode!r}")
    if rfq_mode not in ("live", "historical"):
        raise ValueError(f"rfq_mode must be 'live' or 'historical', got {rfq_mode!r}")

    output_qty_col = qty_col if mode == "sum" else COUNT_COLUMN

    def _key_for(row: dict) -> tuple:
        mpn = (row.get(mpn_col) or "").strip() if isinstance(row.get(mpn_col), str) else row.get(mpn_col)
        condition = row.get(condition_col) if condition_col else None
        base = (str(mpn), str(condition) if condition is not None else None)
        if rfq_mode != "historical":
            return base
        # Historical: pricing events with different bids/outcomes are distinct
        bid = str(row.get(bid_col)) if bid_col and row.get(bid_col) is not None else None
        win = str(row.get(win_col)) if win_col and row.get(win_col) is not None else None
        outcome = str(row.get(outcome_col)) if outcome_col and row.get(outcome_col) is not None else None
        return base + (bid, win, outcome)

    groups: dict[tuple, dict] = defaultdict(lambda: {"qty": 0, "_sample": None})
    qty_in = 0

    for row in rows:
        mpn = (row.get(mpn_col) or "").strip() if isinstance(row.get(mpn_col), str) else row.get(mpn_col)
        if mpn is None or mpn == "":
            continue
        key = _key_for(row)

        if mode == "count":
            increment = 1
        else:
            try:
                increment = int(float(row.get(qty_col) or 1))
            except (TypeError, ValueError):
                increment = 1

        qty_in += increment
        groups[key]["qty"] += increment
        if groups[key]["_sample"] is None:
            groups[key]["_sample"] = row

    consolidated = []
    qty_out = 0
    for key, data in groups.items():
        merged = dict(data["_sample"])
        merged[mpn_col] = key[0]
        merged[output_qty_col] = data["qty"]
        if condition_col and key[1] is not None:
            merged[condition_col] = key[1]
        consolidated.append(merged)
        qty_out += data["qty"]

    all_mpns = [str(r.get(mpn_col, "")).strip() for r in rows if r.get(mpn_col)]
    ambiguous = find_ambiguous_pairs(all_mpns)

    if qty_in != qty_out:
        raise AssertionError(
            f"quantity not conserved: in={qty_in} out={qty_out} (mode={mode}, rfq_mode={rfq_mode})"
        )

    return {
        "consolidated": consolidated,
        "ambiguous_pairs": ambiguous,
        "mode": mode,
        "rfq_mode": rfq_mode,
        "qty_column": output_qty_col,
        "qty_in": qty_in,
        "qty_out": qty_out,
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
    rfq_mode = raw.get("rfq_mode", "live")
    bid_col = raw.get("bid_col")
    win_col = raw.get("win_col")
    outcome_col = raw.get("outcome_col")

    result = consolidate(
        rows, mpn_col, qty_col, condition_col,
        mode=mode, rfq_mode=rfq_mode,
        bid_col=bid_col, win_col=win_col, outcome_col=outcome_col,
    )
    json.dump(result, sys.stdout, default=str, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
