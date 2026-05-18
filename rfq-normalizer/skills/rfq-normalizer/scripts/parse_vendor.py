#!/usr/bin/env python3
"""Parse a vendor RFQ spreadsheet (xlsx or csv) and emit normalized rows.

Output: prints JSON to stdout with shape:
    {
      "headers": ["Part #", "Qty", "Description", ...],
      "rows": [{"Part #": "ABC123", "Qty": 10, ...}, ...],
      "sheet_names": ["Sheet1", ...]    # xlsx only
    }

Usage:
    python parse_vendor.py path/to/vendor.xlsx [--sheet "Sheet1"]
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


def parse_xlsx(path: Path, sheet: str | None) -> dict:
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True, read_only=True)
    sheet_names = wb.sheetnames
    target = wb[sheet] if sheet else wb[sheet_names[0]]

    rows_iter = target.iter_rows(values_only=True)
    headers = [str(h).strip() if h is not None else "" for h in next(rows_iter, [])]
    headers = [h for h in headers if h]  # drop trailing blanks

    rows = []
    for raw in rows_iter:
        if not any(cell is not None and str(cell).strip() for cell in raw):
            continue  # skip blank rows
        row = {}
        for i, h in enumerate(headers):
            row[h] = raw[i] if i < len(raw) else None
        rows.append(row)

    return {"headers": headers, "rows": rows, "sheet_names": sheet_names}


def parse_csv(path: Path) -> dict:
    import csv

    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = [h.strip() for h in (reader.fieldnames or []) if h.strip()]
        rows = [
            {h: row.get(h) for h in headers}
            for row in reader
            if any((v or "").strip() for v in row.values())
        ]
    return {"headers": headers, "rows": rows, "sheet_names": []}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--sheet", default=None)
    args = ap.parse_args()

    if not args.path.exists():
        print(f"ERROR: file not found: {args.path}", file=sys.stderr)
        return 1

    suffix = args.path.suffix.lower()
    if suffix == ".xlsx":
        out = parse_xlsx(args.path, args.sheet)
    elif suffix == ".csv":
        out = parse_csv(args.path)
    else:
        print(f"ERROR: unsupported file type {suffix}", file=sys.stderr)
        return 1

    json.dump(out, sys.stdout, default=str, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
