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


from split_description import split_row


def test_split_row_merges_across_text_columns():
    row = {
        "MPN": "ST12000NM006J",
        "Description": "Seagate Exos",
        "Size": "12TB 7.2K SAS-12GBPS",
    }
    result = split_row(row, text_columns=["Description", "Size"])
    assert result["size"] == "12TB"
    assert result["interface"] == "SAS"


def test_split_row_uses_description_only_when_others_unspecified():
    row = {"Description": "1.6TB SATA SSD 2.5\""}
    result = split_row(row, text_columns=["Description"])
    assert result["size"] == "1.6TB"
    assert result["interface"] == "SATA"
    assert result["drive_type"] == "SSD"
    assert result["form_factor"] == "2.5in"


def test_split_row_skips_missing_columns():
    row = {"Description": "480GB SSD"}
    result = split_row(row, text_columns=["Description", "Size", "Notes"])
    assert result["size"] == "480GB"
