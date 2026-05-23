"""Tests for normalize_condition (v0.7 Fix 7).

Covers grade letters, grade-suffix words ("B grade"), and condition words
("Good") in one entry point, never guessing on unknown input.
"""
from __future__ import annotations

from normalize_condition import normalize_condition


def test_grade_with_suffix():
    assert normalize_condition("B grade") == "used_good"
    assert normalize_condition("Grade B") == "used_good"
    assert normalize_condition("A grade") == "used_like_new"


def test_bare_grade_letters_still_work():
    assert normalize_condition("A+") == "used_like_new"
    assert normalize_condition("C") == "used_fair"
    assert normalize_condition("D") == "for_parts"


def test_condition_words():
    assert normalize_condition("Good") == "used_good"
    assert normalize_condition("used like new") == "used_like_new"
    assert normalize_condition("refurb") == "refurbished"
    assert normalize_condition("for parts") == "for_parts"
    assert normalize_condition("New Sealed") == "new"


def test_unknown_returns_none():
    assert normalize_condition("xyz") is None
    assert normalize_condition("") is None
    assert normalize_condition(None) is None


def test_whitespace_and_case_insensitive():
    assert normalize_condition("  b GRADE  ") == "used_good"
    assert normalize_condition("GOOD") == "used_good"
