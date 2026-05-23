"""Tests for analyze_columns row-per-item detection (v0.7 Fix 8).

A sparse serial column must not, on its own, force `count` mode. Row-per-item
is chosen when there's no Quantity column AND either a *substantially-filled*
unique serial column OR the sheet is a plain inventory list (no bid/outcome).
"""
from __future__ import annotations

from analyze_columns import analyze


def _rows(headers, data):
    return [dict(zip(headers, row)) for row in data]


def test_sparse_serial_with_bid_does_not_force_count():
    # 10 rows, serial filled on only 1 (10%), and a Bid Price column present.
    # The old logic chose count off the lone unique serial; it must now be sum.
    headers = ["MPN", "Bid Price", "Outcome", "Serial"]
    data = [[f"M{i}", 10.0, "won", ("SN123" if i == 0 else None)] for i in range(10)]
    result = analyze(headers, _rows(headers, data))
    assert result.suggested_consolidation_mode == "sum"


def test_plain_inventory_no_qty_resolves_to_count():
    # No qty, no bid/outcome, sparse serial → count for the plain-inventory reason.
    headers = ["Brand", "Model", "Capacity", "Serial"]
    data = [["Hitachi", "HUA723020ALA640", "2TB", ("SN%d" % i if i < 3 else None)]
            for i in range(10)]
    result = analyze(headers, _rows(headers, data))
    assert result.suggested_consolidation_mode == "count"
    assert any("inventory" in w.lower() for w in result.warnings)


def test_substantial_unique_serial_resolves_to_count():
    # Serial filled on 9/10 rows and unique → count via the serial signal,
    # even though a bid column is present.
    headers = ["MPN", "Bid Price", "Serial"]
    data = [[f"M{i}", 10.0, (f"SN{i}" if i < 9 else None)] for i in range(10)]
    result = analyze(headers, _rows(headers, data))
    assert result.suggested_consolidation_mode == "count"
    assert any("serial" in w.lower() for w in result.warnings)


def test_quantity_column_forces_sum():
    headers = ["MPN", "Quantity", "Serial"]
    data = [[f"M{i}", 5, f"SN{i}"] for i in range(10)]
    result = analyze(headers, _rows(headers, data))
    assert result.suggested_consolidation_mode == "sum"
