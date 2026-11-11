"""Tests for the agent tools, run against a freshly generated sample database
(the `db_path` fixture in conftest.py)."""

import sqlite3

import pytest

from data.create_db import build_database
from sql_agent.tools import connect_readonly, describe_table, list_tables, run_sql

EXPECTED_TABLES = ["categories", "customers", "order_items", "orders", "products", "returns"]


def test_list_tables(db_path):
    assert list_tables(db_path) == EXPECTED_TABLES


def test_describe_table_shows_columns_fks_and_samples(db_path):
    text = describe_table("orders", db_path)
    assert "Table: orders" in text
    assert "order_id (INTEGER) PRIMARY KEY" in text
    assert "customer_id -> customers.customer_id" in text
    assert "Sample rows:" in text


def test_describe_unknown_table_lists_alternatives(db_path):
    text = describe_table("orderz", db_path)
    assert text.startswith("ERROR")
    assert "orders" in text


# The table name is only interpolated into SQL after an exact-match check.
def test_describe_table_rejects_injection_attempt(db_path):
    text = describe_table('orders"; DROP TABLE orders; --', db_path)
    assert text.startswith("ERROR")
    assert "orders" in list_tables(db_path)


def test_run_sql_success(db_path):
    result = run_sql("SELECT COUNT(*) AS n FROM customers", db_path)
    assert result.ok
    assert result.columns == ["n"]
    assert result.rows == [(206,)]  # 200 customers + 6 duplicates
    assert "n\n206" == result.to_text()


def test_run_sql_returns_error_text_for_bad_sql(db_path):
    result = run_sql("SELECT nonexistent_column FROM customers", db_path)
    assert not result.ok
    assert "nonexistent_column" in result.error
    assert result.to_text().startswith("ERROR")


def test_run_sql_blocks_writes_via_guard(db_path):
    result = run_sql("DELETE FROM customers", db_path)
    assert not result.ok
    assert "safety guard" in result.error
    assert run_sql("SELECT COUNT(*) FROM customers", db_path).rows == [(206,)]


def test_run_sql_truncates_rows(db_path):
    result = run_sql("SELECT * FROM orders", db_path, max_rows=10)
    assert result.ok and result.truncated
    assert len(result.rows) == 10
    assert "truncated" in result.to_text()


def test_run_sql_no_truncation_flag_when_exactly_at_limit(db_path):
    result = run_sql("SELECT * FROM categories", db_path, max_rows=8)  # exactly 8 categories
    assert result.ok and not result.truncated and len(result.rows) == 8


def test_run_sql_empty_result(db_path):
    result = run_sql("SELECT * FROM customers WHERE customer_id < 0", db_path)
    assert result.ok and result.rows == []
    assert "0 rows" in result.to_text()


def test_run_sql_timeout(db_path):
    # An infinite recursive CTE: only the timeout (layer 3) can stop it.
    runaway = (
        "WITH RECURSIVE r(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM r) "
        "SELECT COUNT(*) FROM r"
    )
    result = run_sql(runaway, db_path, timeout_seconds=0.3)
    assert not result.ok
    assert "time limit" in result.error


def test_connection_is_read_only_even_without_guard(db_path):
    """Layer 2: if the guard were bypassed, SQLite itself still refuses to write."""
    conn = connect_readonly(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM customers")
    finally:
        conn.close()


def test_missing_database_has_helpful_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="create_db"):
        list_tables(tmp_path / "nope.db")


# Same seed -> same data, so eval answers stay reproducible across machines.
def test_database_is_deterministic(tmp_path):
    a = build_database(tmp_path / "a.db")
    b = build_database(tmp_path / "b.db")
    query = "SELECT SUM(total), COUNT(*) FROM orders"
    assert run_sql(query, a).rows == run_sql(query, b).rows


# Guards against someone "cleaning" the data: the mess is what tests the agent.
def test_sample_data_has_intended_messiness(db_path):
    null_emails = run_sql("SELECT COUNT(*) FROM customers WHERE email IS NULL", db_path).rows[0][0]
    dupes = run_sql(
        "SELECT COUNT(*) FROM (SELECT email FROM customers WHERE email IS NOT NULL "
        "GROUP BY email HAVING COUNT(*) > 1)",
        db_path,
    ).rows[0][0]
    null_discounts = run_sql("SELECT COUNT(*) FROM orders WHERE discount IS NULL", db_path).rows[0][0]
    assert null_emails > 0
    assert dupes == 6
    assert null_discounts > 0
