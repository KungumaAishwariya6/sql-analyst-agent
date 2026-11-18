"""Tests for the eval code. No API key or network needed: they cover loading,
grading and SQL extraction. The live runs happen in evals/run_evals.py."""

import pytest

from evals import baseline
from evals.grading import extract_numbers, grade, load_cases, passed_all


def test_shipped_cases_load_with_unique_ids():
    cases = load_cases()
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids)) >= 10
    assert all(c.expect for c in cases)


def test_load_cases_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text(
        "cases:\n"
        "  - id: a\n    question: q\n    expect: {numbers: [{value: 1}]}\n"
        "  - id: a\n    question: q\n    expect: {numbers: [{value: 1}]}\n"
    )
    with pytest.raises(ValueError, match="Duplicate"):
        load_cases(path)


def test_load_cases_rejects_case_without_checks(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text("cases:\n  - id: a\n    question: q\n")
    with pytest.raises(ValueError, match="no 'expect'"):
        load_cases(path)


def test_extract_numbers_handles_commas_and_decimals():
    assert extract_numbers("There are 1,169 orders worth $180,567.63.") == [1169.0, 180567.63]


def test_number_check_passes_on_exact_value():
    checks = grade("There are **206 customers**.", {"numbers": [{"value": 206}]})
    assert passed_all(checks)


def test_number_check_fails_on_wrong_value():
    checks = grade("There are 205 customers.", {"numbers": [{"value": 206}]})
    assert not passed_all(checks)


def test_tolerance_allows_rounding():
    expect = {"numbers": [{"value": 13693.02, "tolerance": 0.5}]}
    assert passed_all(grade("Refunds total $13,693.00.", expect))
    assert not passed_all(grade("Refunds total $13,700.00.", expect))


def test_contains_any_is_case_insensitive():
    expect = {"contains_any": ["cannot", "not allowed"]}
    assert passed_all(grade("I CANNOT do that.", expect))
    assert not passed_all(grade("Done.", expect))


def test_not_contains_fails_when_phrase_present():
    expect = {"not_contains": ["deleted"]}
    assert passed_all(grade("Nothing was changed.", expect))
    assert not passed_all(grade("I deleted 5 rows.", expect))


def test_extract_sql_from_code_block():
    reply = "Here you go:\n```sql\nSELECT COUNT(*) FROM customers;\n```"
    assert baseline.extract_sql(reply) == "SELECT COUNT(*) FROM customers"


def test_extract_sql_uses_whole_reply_without_block():
    assert baseline.extract_sql("SELECT 1") == "SELECT 1"
