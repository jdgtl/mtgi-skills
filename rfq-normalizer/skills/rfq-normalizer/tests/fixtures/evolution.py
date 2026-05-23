"""Shared fixture mirroring the "Evolution E-Cycle – Combined Drive Inventory" file.

The real file (1,403 drives) surfaced the v0.7 issues. This fixture reproduces
its *shape* in miniature so the fixes can be tested without a 1,403-row binary:

  - two title/banner rows + a blank row above the real header (header on row 4)
  - the 12 real headers
  - a model-family "MPN" (the Model column) that repeats across capacities and
    prices — i.e. NOT a unique manufacturer part number per physical unit
  - "Hard Drive" / "SSD" vendor drive-type spellings
  - HGST / Hitachi / HP brands
  - a sparse Serial column (only some rows have one)
  - a trailing "TOTAL: N drives" summary footer with a number in the Price column
"""
from __future__ import annotations

from pathlib import Path

# The 12 real headers, in sheet order (header row of the real file).
HEADERS = [
    "Source", "Brand", "Model", "Capacity", "Drive Type", "Interface",
    "Form Factor", "Health / Grade", "Tested", "Price", "Serial", "Notes",
]

# Banner rows that sit above the real header in the source sheet.
BANNER_ROWS = [
    ["Evolution E-Cycle"],
    ["Combined Drive Inventory"],
    [],  # blank spacer row
]


def evolution_data_rows() -> list[dict]:
    """Representative data rows as dicts keyed by HEADERS.

    Model HUA723020ALA640 repeats 3× at the same spec/price (a clean
    consolidatable group); HUS726040ALE610 repeats 2× at *different* prices
    (a true same-spec price conflict); the rest are singletons. Serial is
    populated on only a few rows (sparse, ~30%).
    """
    return [
        # Model-family MPN repeating, same spec + price → consolidatable group.
        _row("ListA", "Hitachi", "HUA723020ALA640", "2TB", "Hard Drive", "SATA", "3.5\"", "B grade", "Yes", 18.00, "JK1101YYG1234A"),
        _row("ListA", "Hitachi", "HUA723020ALA640", "2TB", "Hard Drive", "SATA", "3.5\"", "B grade", "Yes", 18.00, None),
        _row("ListA", "Hitachi", "HUA723020ALA640", "2TB", "Hard Drive", "SATA", "3.5\"", "B grade", "Yes", 18.00, None),
        # Same model, SAME spec, DIFFERENT price → true conflict if consolidated.
        _row("ListB", "HGST", "HUS726040ALE610", "4TB", "Hard Drive", "SATA", "3.5\"", "Good", "Yes", 25.00, "JK1102ZZG5678B"),
        _row("ListB", "HGST", "HUS726040ALE610", "4TB", "Hard Drive", "SATA", "3.5\"", "Good", "Yes", 30.00, None),
        # SSD singletons.
        _row("ListB", "HP", "VK000960GWTTH", "960GB", "SSD", "SATA", "2.5\"", "A", "Yes", 42.00, "BTHC1234ABCD"),
        _row("ListA", "Sandisk", "SDLF1DAR-960G", "960GB", "Solid State Drive", "SATA", "2.5\"", "A", "Yes", 38.00, None),
        # HP Enterprise brand variant; model-family repeated once at one price.
        _row("ListA", "HP Enterprise", "EG0900JFCKB", "900GB", "Hard Drive", "SAS", "2.5\"", "B", "Yes", 15.00, None),
        _row("ListA", "HP Enterprise", "EG0900JFCKB", "900GB", "Hard Drive", "SAS", "2.5\"", "B", "Yes", 15.00, None),
    ]


def _row(source, brand, model, capacity, drive_type, interface, form_factor,
         grade, tested, price, serial, notes="") -> dict:
    return {
        "Source": source, "Brand": brand, "Model": model, "Capacity": capacity,
        "Drive Type": drive_type, "Interface": interface, "Form Factor": form_factor,
        "Health / Grade": grade, "Tested": tested, "Price": price,
        "Serial": serial, "Notes": notes,
    }


def write_evolution_xlsx(path: Path, *, with_banners: bool = True,
                         with_total_footer: bool = True) -> Path:
    """Write the fixture to an xlsx, optionally with banner rows + TOTAL footer."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Combined Drive Inventory"

    if with_banners:
        for banner in BANNER_ROWS:
            ws.append(banner)

    ws.append(HEADERS)
    rows = evolution_data_rows()
    for r in rows:
        ws.append([r[h] for h in HEADERS])

    if with_total_footer:
        footer = [""] * len(HEADERS)
        footer[0] = f"TOTAL: {len(rows)} drives"
        footer[HEADERS.index("Price")] = sum(
            (r["Price"] or 0) for r in rows
        )
        ws.append(footer)

    wb.save(path)
    return path
