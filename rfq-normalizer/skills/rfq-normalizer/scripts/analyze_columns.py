#!/usr/bin/env python3
"""Inspect a parsed vendor sheet and emit a structural assessment.

Three signals are useful to the agent BEFORE it starts mapping columns:

1. **Always-blank columns** — vendor probably forgot to fill them. Warn the
   operator: "the 'Type' column is empty in 158/158 rows. Drop it or are
   you missing data?"

2. **Row-per-item vs row-per-line layout** — if there's a unique-per-row
   serial-number-style column AND no explicit Quantity column, every row
   is one physical item and we consolidate by counting rows. Otherwise
   each row already represents a line with its own quantity.

3. **Live vs historical mode hint** — if the sheet has no Bid Price column
   and no Outcome column, it's a "for bid" sourcing list (live mode), not
   a historical record. Operator should import as `live` not `historical`.

Input  (stdin or --input): {"headers": [...], "rows": [...]}
Output (stdout):           {assessment block — see ColumnAnalysis below}
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from typing import Any

# Columns commonly used for "one physical item per row" identification.
SERIAL_PATTERNS = [
    re.compile(r"^serial.?(no|number|num)?$", re.I),
    re.compile(r"^s/?n$", re.I),
    re.compile(r"^asset.?(tag|id|number)?$", re.I),
    re.compile(r"^unit.?(id|tag)?$", re.I),
    re.compile(r"^imei$", re.I),
]

# Columns that, if present and populated, mean each row is an aggregated line.
QTY_PATTERNS = [
    re.compile(r"^qty$", re.I),
    re.compile(r"^quantity$", re.I),
    re.compile(r"^qnt$", re.I),
    re.compile(r"^count$", re.I),
    re.compile(r"^units$", re.I),
]

# Historical-mode signal columns.
BID_PRICE_PATTERNS = [
    re.compile(r"^bid.?price", re.I),
    re.compile(r"^our.?bid", re.I),
    re.compile(r"^unit.?price", re.I),
    re.compile(r"^bid$", re.I),
]
OUTCOME_PATTERNS = [
    re.compile(r"^outcome$", re.I),
    re.compile(r"^result$", re.I),
    re.compile(r"^status$", re.I),
    re.compile(r"^won.?lost", re.I),
]


@dataclass
class ColumnStat:
    name: str
    populated: int
    total: int
    fill_rate: float           # 0.0 (all blank) → 1.0 (all populated)
    unique_values: int         # distinct non-blank values seen
    is_always_blank: bool      # fill_rate <= 0.05
    looks_unique_per_row: bool # unique_values / populated > 0.95


@dataclass
class ColumnAnalysis:
    total_rows: int
    columns: list[ColumnStat]
    warnings: list[str]
    suggested_consolidation_mode: str  # 'count' or 'sum'
    suggested_rfq_mode: str            # 'live' or 'historical'
    detected: dict[str, str | None]    # detected column names by role


def _match_first(patterns: list[re.Pattern], headers: list[str]) -> str | None:
    for h in headers:
        if any(p.match(h.strip()) for p in patterns):
            return h
    return None


def _is_blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and not v.strip():
        return True
    return False


def analyze(headers: list[str], rows: list[dict]) -> ColumnAnalysis:
    total = len(rows)
    column_stats: list[ColumnStat] = []
    warnings: list[str] = []

    for header in headers:
        non_blank_values = [r.get(header) for r in rows if not _is_blank(r.get(header))]
        populated = len(non_blank_values)
        unique = len(set(str(v) for v in non_blank_values))
        fill_rate = populated / total if total else 0.0
        is_blank = fill_rate <= 0.05
        unique_per_row = (unique / populated) > 0.95 if populated else False
        column_stats.append(ColumnStat(
            name=header,
            populated=populated,
            total=total,
            fill_rate=round(fill_rate, 3),
            unique_values=unique,
            is_always_blank=is_blank,
            looks_unique_per_row=unique_per_row,
        ))
        if is_blank and total >= 5:
            warnings.append(
                f"Column '{header}' is empty in {total - populated}/{total} rows — "
                f"vendor may have forgotten to fill it. Drop or request fresh data."
            )

    # Detect roles
    serial_col = _match_first(SERIAL_PATTERNS, headers)
    qty_col = _match_first(QTY_PATTERNS, headers)
    bid_price_col = _match_first(BID_PRICE_PATTERNS, headers)
    outcome_col = _match_first(OUTCOME_PATTERNS, headers)

    # Row-per-item detection. A sparse serial column must NOT be decisive on its
    # own (uniqueness is measured over populated cells, so a 7%-filled serial can
    # look "unique per row"). Weight the serial signal by fill rate, and also
    # treat a plain inventory list (no qty, no bid/outcome) as row-per-item.
    SERIAL_FILL_FLOOR = 0.50
    serial_stat = next((s for s in column_stats if s.name == serial_col), None)
    serial_signal = (
        serial_col is not None
        and serial_stat is not None
        and serial_stat.looks_unique_per_row
        and serial_stat.fill_rate >= SERIAL_FILL_FLOOR
    )
    # Live vs historical detection: no bid/outcome → live (parts being offered).
    is_historical = bid_price_col is not None or outcome_col is not None
    suggested_rfq_mode = "historical" if is_historical else "live"

    # Plain inventory list: no quantity column and no bid/outcome columns → each
    # row is one physical unit being inventoried, not an aggregated bid line.
    plain_inventory_signal = qty_col is None and not is_historical

    is_row_per_item = qty_col is None and (serial_signal or plain_inventory_signal)
    suggested_consolidation = "count" if is_row_per_item else "sum"

    if is_row_per_item:
        if serial_signal:
            reason = (
                f"column '{serial_col}' is unique per row and substantially filled "
                f"({serial_stat.fill_rate:.0%}), and no quantity column is present"
            )
        else:
            reason = (
                "no quantity column and no bid/outcome columns — this is a plain "
                "inventory list"
            )
        warnings.append(
            f"Detected ROW-PER-ITEM layout ({reason}). Each row will be counted as 1 unit."
        )

    if not is_historical:
        warnings.append(
            "No Bid Price or Outcome column detected — this looks like a 'live' RFQ "
            "(parts available for bid), not a historical record. Output will omit "
            "Bid Price / Outcome columns; import as `live` mode in the wizard."
        )

    return ColumnAnalysis(
        total_rows=total,
        columns=column_stats,
        warnings=warnings,
        suggested_consolidation_mode=suggested_consolidation,
        suggested_rfq_mode=suggested_rfq_mode,
        detected={
            "serial_column": serial_col,
            "qty_column": qty_col,
            "bid_price_column": bid_price_col,
            "outcome_column": outcome_col,
        },
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=None, help="JSON file (default: stdin)")
    args = ap.parse_args()
    raw = json.load(open(args.input) if args.input else sys.stdin)
    result = analyze(raw["headers"], raw["rows"])
    # asdict on the dataclass + manual unpacking of column list
    out = {
        "total_rows": result.total_rows,
        "columns": [asdict(c) for c in result.columns],
        "warnings": result.warnings,
        "suggested_consolidation_mode": result.suggested_consolidation_mode,
        "suggested_rfq_mode": result.suggested_rfq_mode,
        "detected": result.detected,
    }
    json.dump(out, sys.stdout, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
