"""End-to-end regression covering the issues seen in the AGIS session:
- decimal GB sizes (480.1 GB → 480GB)
- Size column mining (SAS interface from Size, not Description)
- historical consolidation keeps distinct bid events
- brand-prefix stripping (INTEL SSDSC2BB012T6 → SSDSC2BB012T6)
- case-collision ambiguity detection (303-...B-02 vs 303-...b-02)
- quantity conservation
"""
import json
from pathlib import Path

from consolidate_duplicates import consolidate
from mpn_patterns import strip_brand_prefix
from split_description import split_row

FIXTURE = Path(__file__).parent / "fixtures" / "agis-sample.json"


def _load_fixture():
    return json.loads(FIXTURE.read_text())


def test_decimal_size_normalized():
    data = _load_fixture()
    sku_row = next(r for r in data["rows"] if r["MPN"].startswith("303-276-000B"))
    out = split_row(sku_row, text_columns=["Description", "Size"])
    assert out["size"] == "480GB"


def test_size_column_mining_recovers_sas_interface():
    data = _load_fixture()
    exos_row = next(r for r in data["rows"] if r["MPN"] == "ST12000NM006J")
    out = split_row(exos_row, text_columns=["Description", "Size"])
    assert out["interface"] == "SAS"


def test_historical_keeps_distinct_bid_events():
    data = _load_fixture()
    result = consolidate(
        data["rows"], mpn_col="MPN", qty_col="Quantity",
        condition_col=None, mode="sum", rfq_mode="historical",
        bid_col="Bid Price", win_col="Winning Bid", outcome_col="Outcome",
    )
    # HUS726T6TALE6L4 has two rows at different (Bid Price=55) and (Bid Price=58)
    # — must stay 2 rows, not collapse to 1.
    hus_rows = [r for r in result["consolidated"] if r["MPN"] == "HUS726T6TALE6L4"]
    assert len(hus_rows) == 2


def test_brand_prefix_stripped():
    cleaned, brand = strip_brand_prefix("INTEL SSDSC2BB012T6")
    assert cleaned == "SSDSC2BB012T6"
    assert brand == "INTEL"


def test_case_collision_surfaces_as_ambiguous():
    data = _load_fixture()
    result = consolidate(
        data["rows"], mpn_col="MPN", qty_col="Quantity",
        condition_col=None, mode="sum", rfq_mode="historical",
        bid_col="Bid Price", win_col="Winning Bid", outcome_col="Outcome",
    )
    pairs = result["ambiguous_pairs"]
    assert any(
        "303-276-000B-02" in (p["mpn_a"], p["mpn_b"])
        and "303-276-000b-02" in (p["mpn_a"], p["mpn_b"])
        for p in pairs
    )


def test_quantity_conserved():
    data = _load_fixture()
    expected_in = sum(r["Quantity"] for r in data["rows"])
    result = consolidate(
        data["rows"], mpn_col="MPN", qty_col="Quantity",
        condition_col=None, mode="sum", rfq_mode="historical",
        bid_col="Bid Price", win_col="Winning Bid", outcome_col="Outcome",
    )
    assert result["qty_in"] == expected_in
    assert result["qty_out"] == expected_in
