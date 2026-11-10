import pytest

from sql_agent.guard import UnsafeSQLError, validate_sql


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM customers",
        "select count(*) from orders;",
        "  SELECT 1  ;  ",
        "WITH t AS (SELECT 1 AS x) SELECT x FROM t",
        "SELECT name FROM products WHERE name = 'DROP TABLE x'",       # keyword inside a string
        "SELECT \"update\" FROM t",                                     # keyword as quoted identifier
        "SELECT update_date, deleted_flag FROM t",                      # keyword as part of a longer name
        "SELECT 'it''s; fine' AS s",                                    # escaped quote and ; inside string
        "SELECT 1 -- DROP TABLE customers",                             # keyword inside a comment
        "SELECT /* DELETE FROM x */ 1",
        "SELECT replace(name, 'a', 'b') FROM products",                 # REPLACE() is a normal function
    ],
)
def test_allows_read_only_queries(query):
    assert validate_sql(query)


@pytest.mark.parametrize(
    "query",
    [
        "DROP TABLE customers",
        "DELETE FROM orders",
        "UPDATE orders SET total = 0",
        "INSERT INTO customers VALUES (1)",
        "CREATE TABLE x (a int)",
        "ALTER TABLE orders ADD COLUMN x int",
        "ATTACH DATABASE 'other.db' AS o",
        "PRAGMA table_info(orders)",
        "SELECT 1; DROP TABLE customers",                               # stacked statements
        "SELECT 1; SELECT 2",
        "SELECT 1 /* hidden */ ; DELETE FROM orders",                   # comment between statements
        "WITH t AS (SELECT 1) DELETE FROM orders",                      # forbidden keyword after WITH
        "SELECT load_extension('evil')",
        "",
        "   ",
        "-- just a comment",
        "EXPLAIN SELECT 1",                                             # not on the allow-list
        "SELECT 'unterminated",
        "SELECT 1 /* unterminated",
    ],
)
def test_blocks_unsafe_queries(query):
    with pytest.raises(UnsafeSQLError):
        validate_sql(query)


def test_strips_trailing_semicolon():
    assert validate_sql("SELECT 1;") == "SELECT 1"
