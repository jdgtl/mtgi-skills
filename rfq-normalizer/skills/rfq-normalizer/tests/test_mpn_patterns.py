from mpn_patterns import score_mpn, strip_brand_prefix


def test_intel_ssd_recognized():
    s = score_mpn("SSDSC2BB012T6")
    assert s.has_known_prefix


def test_micron_ssd_recognized():
    s = score_mpn("MTFDDAK480TDS")
    assert s.has_known_prefix


def test_toshiba_kioxia_kpm():
    s = score_mpn("KPM5XRUG960G")
    assert s.has_known_prefix


def test_toshiba_kioxia_kxg():
    s = score_mpn("KXG60ZNV512G")
    assert s.has_known_prefix


def test_hgst_oem_prefix():
    s = score_mpn("0F22811")
    assert s.has_known_prefix


def test_sandisk_sdfam():
    s = score_mpn("SDFAB-960G-XXX")
    assert s.has_known_prefix


def test_strip_intel_prefix():
    cleaned, original = strip_brand_prefix("INTEL SSDSC2BB012T6")
    assert cleaned == "SSDSC2BB012T6"
    assert original == "INTEL SSDSC2BB012T6"


def test_strip_toshiba_prefix():
    cleaned, original = strip_brand_prefix("TOSHIBA AL15SEB060N")
    assert cleaned == "AL15SEB060N"


def test_strip_hgst_prefix():
    cleaned, original = strip_brand_prefix("HGST HUS726T6TALE6L4")
    assert cleaned == "HUS726T6TALE6L4"


def test_no_strip_when_no_prefix():
    cleaned, original = strip_brand_prefix("SSDSC2BB012T6")
    assert cleaned == "SSDSC2BB012T6"
    assert original == "SSDSC2BB012T6"


def test_no_strip_for_unknown_prefix():
    # Vendor brand prefixes outside the allowlist must NOT be stripped.
    cleaned, original = strip_brand_prefix("ACME WIDGET-42")
    assert cleaned == "ACME WIDGET-42"


def test_sandisk_sdlf_multi_letter():
    s = score_mpn("SDLFAAAR-019T-1HA1")
    assert s.has_known_prefix
