# SQL Analyst Agent

Ask questions about a database in plain English. A LangGraph agent inspects the
schema, writes SQL, runs it read-only, recovers from its own errors, and answers.

> **Status:** Day 1 of 3 complete (database, safety guard, tools, tests).
> The agent (Day 2) and the eval suite (Day 3) are coming next.

## Why an agent and not a single prompt?

A single text-to-SQL call works for easy questions. An agent loop helps when the
first query isn't enough: it can discover the schema on demand, read a SQL error
and fix the query, and chain several queries for multi-step questions. Day 3
measures this: single-shot baseline vs. agent loop on the same eval set.

## Project layout

```
data/create_db.py     generates the sample e-commerce SQLite database (seeded, reproducible)
sql_agent/guard.py    SQL safety validator (single read-only SELECT/WITH only)
sql_agent/tools.py    list_tables, describe_table, run_sql
sql_agent/config.py   paths and safety limits
tests/                pytest suite (guard attacks, tools, database)
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python data/create_db.py      # writes data/sample.db
pytest                        # 46 tests
```

## The sample database

Six e-commerce tables: `customers`, `orders`, `order_items`, `products`,
`categories`, `returns` (about 5,000 rows, fixed random seed).

It is intentionally messy, because easy schemas don't test an agent:

- `status` exists in four tables with different meanings.
- `orders.total` (net of discount) vs `order_items.amount` (quantity x unit price).
- NULL emails, 6 duplicate customers (same email, new id), mostly-NULL `orders.discount`.
- Discontinued products that stop selling partway through the date range.

## Safety: three layers

1. **Guard** (`guard.py`): only one `SELECT`/`WITH` statement. Comments are removed
   and string contents blanked before scanning, so `SELECT 'DROP TABLE x'` is fine
   but `SELECT 1; DROP TABLE x` is rejected.
2. **Read-only connection** (`tools.py`): SQLite opened with `mode=ro` and
   `PRAGMA query_only`. Even if the guard had a bug, writes fail.
3. **Limits**: results capped at 100 rows and queries aborted after 5 seconds.

Tool errors are returned as text, not raised, so the agent can read them and retry.
