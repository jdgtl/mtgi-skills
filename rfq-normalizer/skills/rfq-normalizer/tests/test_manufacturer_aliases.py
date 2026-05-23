"""Tests for manufacturer alias normalization (v0.7 Fix 6).

Operator decision: HGST and Hitachi-branded drives canonicalize to Western
Digital (WD acquired Hitachi GST in 2012; these ship as WD/Ultrastar).
"""
from __future__ import annotations

from manufacturer_aliases import normalize_manufacturer, manufacturers_match


def test_hgst_maps_to_western_digital():
    assert normalize_manufacturer("HGST") == "Western Digital"


def test_hitachi_gst_variants_map_to_wd():
    for variant in ("Hitachi GST", "Hitachi Global Storage",
                    "Hitachi Global Storage Technologies", "IBM/Hitachi"):
        assert normalize_manufacturer(variant) == "Western Digital", variant


def test_plain_hitachi_maps_to_wd():
    # Operator-confirmed: plain "Hitachi" drives in this ITAD context are
    # HGST/Ultrastar = Western Digital.
    assert normalize_manufacturer("Hitachi") == "Western Digital"


def test_hgst_and_hitachi_match_each_other():
    assert manufacturers_match("HGST", "Hitachi")
    assert manufacturers_match("Hitachi", "Western Digital")


def test_hp_enterprise_maps_to_hpe():
    assert normalize_manufacturer("HP Enterprise") == "HPE"


def test_sandisk_canonical_casing():
    assert normalize_manufacturer("Sandisk") == "SanDisk"
    assert normalize_manufacturer("SANDISK") == "SanDisk"


def test_wdc_maps_to_western_digital():
    assert normalize_manufacturer("WDC") == "Western Digital"


def test_unrelated_brand_unaffected():
    assert normalize_manufacturer("Seagate") == "Seagate"
    assert not manufacturers_match("Seagate", "Western Digital")


def test_mpn_prefix_consistency_hgst_family():
    # Fix 6: HGST-family MPN prefixes must, after alias normalization, land on WD.
    from mpn_patterns import score_mpn
    assert normalize_manufacturer(score_mpn("0F22811").suggested_manufacturer) == "Western Digital"
    assert normalize_manufacturer(score_mpn("HUS726040ALE610").suggested_manufacturer) == "Western Digital"
