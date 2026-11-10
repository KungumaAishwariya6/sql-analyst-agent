"""The three database tools the agent will use (wrapped for LangGraph on Day 2).

These are plain Python functions on purpose: the agent can only touch the
database through them, so they are the security boundary and can be unit
tested without any LLM.

Design notes:
* Every function returns *text/data*, never raises for a bad query. When a query
  fails, the error message goes back to the agent so it can fix the SQL and
  retry. That feedback loop is what makes this an agent.
* The connection is read-only (mode=ro + PRAGMA query_only), rows are capped,
  and a progress handler aborts queries that run too long.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from sql_agent import config
from sql_agent.guard import UnsafeSQLError, validate_sql


@dataclass
class QueryResult:
    """Outcome of run_sql. Either `error` is set, or `columns`/`rows` are."""

    ok: bool
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    truncated: bool = False
    error: str | None = None

    def to_text(self) -> str:
        """Compact text form the agent reads."""
        if not self.ok:
            return f"ERROR: {self.error}"
        if not self.rows:
            return "Query ran successfully and returned 0 rows."
        lines = [" | ".join(self.columns)]
        lines += [" | ".join("NULL" if v is None else str(v) for v in row) for row in self.rows]
        if self.truncated:
            lines.append(f"... (truncated to the first {len(self.rows)} rows; add a LIMIT or aggregate)")
        return "\n".join(lines)


def connect_readonly(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open the database read-only. Writes fail even if the guard is bypassed."""
    path = Path(db_path or config.DB_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}. Run `python data/create_db.py` first.")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


def list_tables(db_path: Path | str | None = None) -> list[str]:
    """Names of all user tables in the database."""
    conn = connect_readonly(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def describe_table(table_name: str, db_path: Path | str | None = None) -> str:
    """Columns, types, foreign keys and 3 sample rows for one table, as text."""
    tables = list_tables(db_path)
    if table_name not in tables:
        # Only exact, known names are ever interpolated into SQL below.
        return f"ERROR: unknown table '{table_name}'. Available tables: {', '.join(tables)}"

    conn = connect_readonly(db_path)
    try:
        cols = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        fks = conn.execute(f'PRAGMA foreign_key_list("{table_name}")').fetchall()
        cursor = conn.execute(f'SELECT * FROM "{table_name}" LIMIT 3')
        sample_cols = [d[0] for d in cursor.description]
        samples = cursor.fetchall()
    finally:
        conn.close()

    lines = [f"Table: {table_name}", "Columns:"]
    for _cid, name, ctype, notnull, _default, pk in cols:
        flags = []
        if pk:
            flags.append("PRIMARY KEY")
        if notnull and not pk:
            flags.append("NOT NULL")
        lines.append(f"  - {name} ({ctype or 'ANY'}){' ' + ' '.join(flags) if flags else ''}")
    if fks:
        lines.append("Foreign keys:")
        for _id, _seq, ref_table, from_col, to_col, *_ in fks:
            lines.append(f"  - {from_col} -> {ref_table}.{to_col}")
    lines.append("Sample rows:")
    lines.append("  " + " | ".join(sample_cols))
    for row in samples:
        lines.append("  " + " | ".join("NULL" if v is None else str(v) for v in row))
    return "\n".join(lines)


def run_sql(
    query: str,
    db_path: Path | str | None = None,
    max_rows: int | None = None,
    timeout_seconds: float | None = None,
) -> QueryResult:
    """Validate and run a read-only query. Never raises for bad SQL: returns an error result."""
    max_rows = max_rows if max_rows is not None else config.MAX_ROWS
    timeout_seconds = timeout_seconds if timeout_seconds is not None else config.QUERY_TIMEOUT_SECONDS

    try:
        clean = validate_sql(query)
    except UnsafeSQLError as exc:
        return QueryResult(ok=False, error=f"Rejected by safety guard: {exc}")

    conn = connect_readonly(db_path)
    deadline = time.monotonic() + timeout_seconds
    # SQLite calls this every 10,000 VM steps; a non-zero return aborts the query.
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        cursor = conn.execute(clean)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(max_rows + 1)  # one extra row tells us if we truncated
        truncated = len(rows) > max_rows
        return QueryResult(ok=True, columns=columns, rows=rows[:max_rows], truncated=truncated)
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc).lower():
            return QueryResult(ok=False, error=f"Query exceeded the {timeout_seconds}s time limit.")
        return QueryResult(ok=False, error=f"SQLite error: {exc}")
    except sqlite3.Error as exc:
        return QueryResult(ok=False, error=f"SQLite error: {exc}")
    finally:
        conn.close()
