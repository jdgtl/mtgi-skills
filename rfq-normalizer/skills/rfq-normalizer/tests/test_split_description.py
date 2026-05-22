from split_description import extract_size


def test_decimal_gb_rounds_to_marketing_size():
    assert extract_size("Drive 120.03 GB SATA SSD") == "120GB"


def test_decimal_gb_near_480():
    assert extract_size("Capacity 480.1 GB") == "480GB"


def test_integer_gb_unchanged():
    assert extract_size("256 GB drive") == "256GB"


def test_decimal_tb_kept_as_is():
    assert extract_size("1.6 TB SATA SSD") == "1.6TB"


def test_integer_tb_strips_zero():
    assert extract_size("14.0 TB HDD") == "14TB"


def test_no_size_returns_none():
    assert extract_size("Generic widget") is None
