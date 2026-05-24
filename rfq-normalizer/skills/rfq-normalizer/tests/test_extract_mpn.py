"""Tests for extract_mpn — pull the manufacturer part number out of a messy
vendor Model string (v0.8 Change 4)."""
from __future__ import annotations

from extract_mpn import extract_mpn


def test_parenthesized_real_mpn():
    r = extract_mpn("Savvio 10K.3 (ST9300603SS)")
    assert r["mpn"] == "ST9300603SS"
    assert r["is_real_mpn"] is True
    assert r["original"] == "Savvio 10K.3 (ST9300603SS)"


def test_brand_and_family_words_stripped():
    r = extract_mpn("Enterprise Storage WD4000FYYZ")
    assert r["mpn"] == "WD4000FYYZ"
    assert r["is_real_mpn"] is True


def test_prefers_manufacturer_prefix_over_oem_spare():
    # Generic OEM/spare tokens lose to the known Seagate prefix.
    r = extract_mpn("MM1000FBFVR 605832-002 (ST91000640SS)")
    assert r["mpn"] == "ST91000640SS"
    assert r["is_real_mpn"] is True


def test_no_real_mpn_flagged_for_review():
    r = extract_mpn("DC S3500 Series")
    assert r["is_real_mpn"] is False
    assert r["mpn"]  # required column — never blank
    assert r["original"] == "DC S3500 Series"


def test_plain_mpn_passthrough():
    r = extract_mpn("ST9300603SS")
    assert r["mpn"] == "ST9300603SS"
    assert r["is_real_mpn"] is True


def test_pure_numeric_spare_not_chosen():
    # A bare OEM spare number is not a real MPN on its own.
    r = extract_mpn("605832-002")
    assert r["is_real_mpn"] is False


def test_empty_input():
    r = extract_mpn("")
    assert r["is_real_mpn"] is False
    assert r["original"] == ""
