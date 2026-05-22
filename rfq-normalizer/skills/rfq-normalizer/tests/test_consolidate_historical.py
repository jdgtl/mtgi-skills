from consolidate_duplicates import consolidate


def test_historical_keeps_distinct_bid_events():
    rows = [
        {"MPN": "HUS726", "Condition": "used_good", "Quantity": 5,
         "Bid Price": "100", "Winning Bid": "120", "Outcome": "won"},
        {"MPN": "HUS726", "Condition": "used_good", "Quantity": 3,
         "Bid Price": "95",  "Winning Bid": "120", "Outcome": "lost"},
    ]
    result = consolidate(
        rows,
        mpn_col="MPN",
        qty_col="Quantity",
        condition_col="Condition",
        mode="sum",
        rfq_mode="historical",
        bid_col="Bid Price",
        win_col="Winning Bid",
        outcome_col="Outcome",
    )
    assert len(result["consolidated"]) == 2, "distinct bid events must NOT merge"


def test_historical_merges_true_duplicates():
    rows = [
        {"MPN": "HUS726", "Condition": "used_good", "Quantity": 5,
         "Bid Price": "100", "Winning Bid": "120", "Outcome": "won"},
        {"MPN": "HUS726", "Condition": "used_good", "Quantity": 3,
         "Bid Price": "100", "Winning Bid": "120", "Outcome": "won"},
    ]
    result = consolidate(
        rows,
        mpn_col="MPN",
        qty_col="Quantity",
        condition_col="Condition",
        mode="sum",
        rfq_mode="historical",
        bid_col="Bid Price",
        win_col="Winning Bid",
        outcome_col="Outcome",
    )
    assert len(result["consolidated"]) == 1
    assert result["consolidated"][0]["Quantity"] == 8


def test_live_mode_keeps_old_mpn_only_key():
    rows = [
        {"MPN": "HUS726", "Condition": "used_good", "Quantity": 5},
        {"MPN": "HUS726", "Condition": "used_good", "Quantity": 3},
    ]
    result = consolidate(
        rows,
        mpn_col="MPN",
        qty_col="Quantity",
        condition_col="Condition",
        mode="sum",
        rfq_mode="live",
    )
    assert len(result["consolidated"]) == 1
    assert result["consolidated"][0]["Quantity"] == 8


def test_total_quantity_conserved():
    rows = [
        {"MPN": "A", "Quantity": 5, "Bid Price": "10", "Winning Bid": "12", "Outcome": "won"},
        {"MPN": "A", "Quantity": 3, "Bid Price": "10", "Winning Bid": "12", "Outcome": "won"},
        {"MPN": "B", "Quantity": 1, "Bid Price": "20", "Winning Bid": "25", "Outcome": "lost"},
    ]
    result = consolidate(
        rows, mpn_col="MPN", qty_col="Quantity",
        condition_col=None, mode="sum", rfq_mode="historical",
        bid_col="Bid Price", win_col="Winning Bid", outcome_col="Outcome",
    )
    assert result["qty_in"] == 9
    assert result["qty_out"] == 9
