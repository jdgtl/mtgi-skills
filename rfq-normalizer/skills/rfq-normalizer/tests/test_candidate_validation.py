from enrich_mpn import _is_valid_candidate_mpn


def test_rejects_interface_token():
    # "SAS-12GBPS" is an interface spec, not a part number.
    assert _is_valid_candidate_mpn("SAS-12GBPS") is False


def test_rejects_product_family_name():
    # "D3-S4610" is an Intel SSD product family, not a real MPN.
    assert _is_valid_candidate_mpn("D3-S4610") is False


def test_rejects_short_token():
    assert _is_valid_candidate_mpn("ABC123") is False  # < 8 chars


def test_rejects_all_digits():
    assert _is_valid_candidate_mpn("12345678") is False


def test_accepts_plausible_mpn():
    assert _is_valid_candidate_mpn("MZILS3T8HMLH") is True


def test_accepts_dash_separated_mpn():
    assert _is_valid_candidate_mpn("HUS726T6TALE6L4") is True


def test_rejects_common_word():
    assert _is_valid_candidate_mpn("SPECIFICATIONS") is False
