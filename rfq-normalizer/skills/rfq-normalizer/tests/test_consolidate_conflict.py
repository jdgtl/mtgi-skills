"""Tests for consolidation conflict fallback (v0.7 Fix 3).

When consolidation runs and any to-be-merged group disagrees on a must-agree
column (price/capacity/specs), the WHOLE file reverts to single units rather
than silently keeping the first row's values.
"""
from __future__ import annotations

from consolidate_duplicates import consolidate


def test_capacity_conflict_triggers_whole_file_fallback():
    rows = [
        {"MPN": "HUA723020ALA640", "Condition": "used_good", "Capacity": "2TB"},
        {"MPN": "HUA723020ALA640", "Condition": "used_good", "Capacity": "4TB"},
        {"MPN": "OTHER", "Condition": "used_good", "Capacity": "1TB"},
    ]
    result = consolidate(rows, mpn_col="MPN", qty_col=None,
                         condition_col="Condition", mode="count", rfq_mode="live")
    assert result["fell_back_to_single_units"] is True
    assert len(result["consolidated"]) == 3  # nothing merged
    assert all(r["Quantity"] == 1 for r in result["consolidated"])
    assert result["qty_in"] == result["qty_out"] == 3
    assert any("Capacity" in c["columns"] for c in result["conflicts"])


def test_price_conflict_with_custom_must_agree():
    rows = [
        {"MPN": "X", "Condition": "used_good", "Price": 0},
        {"MPN": "X", "Condition": "used_good", "Price": 10},
    ]
    result = consolidate(rows, mpn_col="MPN", qty_col=None,
                         condition_col="Condition", mode="count", rfq_mode="live",
                         must_agree_cols=["Price"])
    assert result["fell_back_to_single_units"] is True
    assert len(result["consolidated"]) == 2


def test_clean_group_still_consolidates():
    rows = [
        {"MPN": "X", "Condition": "used_good", "Capacity": "2TB"},
        {"MPN": "X", "Condition": "used_good", "Capacity": "2TB"},
    ]
    result = consolidate(rows, mpn_col="MPN", qty_col=None,
                         condition_col="Condition", mode="count", rfq_mode="live")
    assert result["fell_back_to_single_units"] is False
    assert len(result["consolidated"]) == 1
    assert result["consolidated"][0]["Quantity"] == 2


def test_sum_mode_fallback_conserves_quantity():
    rows = [
        {"MPN": "X", "Condition": "used_good", "Quantity": 3, "Price": 0},
        {"MPN": "X", "Condition": "used_good", "Quantity": 2, "Price": 10},
    ]
    result = consolidate(rows, mpn_col="MPN", qty_col="Quantity",
                         condition_col="Condition", mode="sum", rfq_mode="live",
                         must_agree_cols=["Price"])
    assert result["fell_back_to_single_units"] is True
    # 5 physical units expanded, quantity conserved.
    assert result["qty_in"] == 5
    assert result["qty_out"] == 5
    assert len(result["consolidated"]) == 5
    assert all(r["Quantity"] == 1 for r in result["consolidated"])


def test_historical_clean_path_no_fallback():
    rows = [
        {"MPN": "A", "Condition": "used_good", "Quantity": 5,
         "Bid Price": "100", "Winning Bid": "120", "Outcome": "won"},
        {"MPN": "A", "Condition": "used_good", "Quantity": 3,
         "Bid Price": "100", "Winning Bid": "120", "Outcome": "won"},
    ]
    result = consolidate(rows, mpn_col="MPN", qty_col="Quantity",
                         condition_col="Condition", mode="sum", rfq_mode="historical",
                         bid_col="Bid Price", win_col="Winning Bid", outcome_col="Outcome")
    assert result["fell_back_to_single_units"] is False
    assert len(result["consolidated"]) == 1
    assert result["consolidated"][0]["Quantity"] == 8
