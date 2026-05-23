"""Tests for parse_vendor header detection + banner/footer handling (v0.7 Fix 1+2)."""
from __future__ import annotations

import csv

import parse_vendor
from fixtures.evolution import HEADERS, evolution_data_rows, write_evolution_xlsx


def test_xlsx_detects_real_header_below_banners(tmp_path):
    path = write_evolution_xlsx(tmp_path / "evo.xlsx")
    out = parse_vendor.parse_xlsx(path, None)
    assert out["headers"] == HEADERS
    assert out["header_row_index"] == 4  # 1-based: 2 banners + 1 blank + header
    # banners reported, blank spacer not counted as a banner
    assert len(out["skipped_banner_rows"]) == 2


def test_xlsx_excludes_total_footer(tmp_path):
    path = write_evolution_xlsx(tmp_path / "evo.xlsx")
    out = parse_vendor.parse_xlsx(path, None)
    assert len(out["rows"]) == len(evolution_data_rows())  # TOTAL row dropped
    assert len(out["dropped_summary_rows"]) == 1
    # No row carries the bogus aggregate price in the Price column.
    assert all("TOTAL" not in str(r.get("Source", "")) for r in out["rows"])
    prices = [r["Price"] for r in out["rows"] if r["Price"] is not None]
    assert max(prices) < 100  # real line items only, not the 20941-style aggregate


def test_header_row_override(tmp_path):
    path = write_evolution_xlsx(tmp_path / "evo.xlsx")
    # Force the wrong row to prove the override is honored.
    out = parse_vendor.parse_xlsx(path, None, header_row=1)
    assert out["header_row_index"] == 1
    assert out["headers"] != HEADERS


def test_no_banner_file_still_parses(tmp_path):
    path = write_evolution_xlsx(tmp_path / "plain.xlsx",
                                with_banners=False, with_total_footer=False)
    out = parse_vendor.parse_xlsx(path, None)
    assert out["headers"] == HEADERS
    assert out["header_row_index"] == 1
    assert len(out["rows"]) == len(evolution_data_rows())


def test_csv_detects_header_and_drops_total(tmp_path):
    path = tmp_path / "evo.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Evolution E-Cycle"])
        w.writerow(["Combined Drive Inventory"])
        w.writerow([])
        w.writerow(HEADERS)
        for r in evolution_data_rows():
            w.writerow([r[h] if r[h] is not None else "" for h in HEADERS])
        total = [""] * len(HEADERS)
        total[0] = "TOTAL: 9 drives"
        total[HEADERS.index("Price")] = "20941"
        w.writerow(total)

    out = parse_vendor.parse_csv(path)
    assert out["headers"] == HEADERS
    assert out["header_row_index"] == 4
    assert len(out["rows"]) == len(evolution_data_rows())
    assert len(out["dropped_summary_rows"]) == 1
