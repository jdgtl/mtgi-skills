"""Coverage for strip_brand_prefix / score_mpn in mpn_patterns."""
from mpn_patterns import strip_brand_prefix, score_mpn


def test_strip_returns_brand_only_for_known_prefix():
    cleaned, brand = strip_brand_prefix("MICRON MTFDDAK480TDS")
    assert cleaned == "MTFDDAK480TDS"
    assert brand == "MICRON"


def test_cleaned_mpn_scores_as_known_prefix():
    # Sanity: bare MPN scores high; that's the whole reason to strip.
    s_raw = score_mpn("INTEL SSDSC2BB012T6")
    s_clean = score_mpn("SSDSC2BB012T6")
    assert s_clean.has_known_prefix
    # The raw form does NOT score as a known prefix.
    assert not s_raw.has_known_prefix
