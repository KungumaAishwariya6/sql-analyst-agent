"""SQL safety guard: the first of three layers that keep the agent read-only.

Layers (defence in depth):
  1. This guard      - only a single SELECT / WITH statement gets through.
  2. Read-only DB    - the connection is opened with mode=ro (see tools.py).
  3. Limits          - row cap and timeout (see tools.py).

The guard works on a "code-only" view of the query: comments are removed and the
contents of string literals / quoted identifiers are blanked out. That way
`SELECT 'DROP TABLE x'` is fine (it is just text) while `SELECT 1; DROP TABLE x`
is rejected, and a keyword hidden behind a comment can't sneak through.
"""

from __future__ import annotations

import re


class UnsafeSQLError(ValueError):
    """Raised when a query is not a single, read-only SELECT statement."""


# Statements / functions that must never appear as code in an agent query.
FORBIDDEN_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "attach", "detach", "pragma", "vacuum", "reindex", "analyze",
    "begin", "commit", "rollback", "savepoint", "release",
    "load_extension",
}

_ALLOWED_START = ("select", "with")


def _code_only(sql: str) -> str:
    """Return `sql` with comments removed and quoted contents blanked out.

    Quoted spans keep their quote characters but lose their contents, so the
    result can be scanned for keywords and semicolons without false positives.
    Raises UnsafeSQLError on unterminated strings or comments.
    """
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if ch == "-" and nxt == "-":  # line comment
            end = sql.find("\n", i)
            i = n if end == -1 else end
            out.append(" ")
        elif ch == "/" and nxt == "*":  # block comment
            end = sql.find("*/", i + 2)
            if end == -1:
                raise UnsafeSQLError("Unterminated comment.")
            i = end + 2
            out.append(" ")
        elif ch in ("'", '"', "`", "["):  # quoted string / identifier
            closer = "]" if ch == "[" else ch
            j = i + 1
            while True:
                if j >= n:
                    raise UnsafeSQLError("Unterminated quoted string or identifier.")
                if sql[j] == closer:
                    # doubled quote ('' or "") is an escaped quote, not the end
                    if closer != "]" and j + 1 < n and sql[j + 1] == closer:
                        j += 2
                        continue
                    break
                j += 1
            out.append(ch + closer)
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def validate_sql(query: str) -> str:
    """Check that `query` is one read-only statement and return it cleaned.

    The returned string has trailing semicolons / whitespace stripped. Comments
    inside the query are left in place (they are harmless once validated).
    Raises UnsafeSQLError with a message the agent can read and act on.
    """
    if not isinstance(query, str) or not query.strip():
        raise UnsafeSQLError("Query is empty.")

    code = _code_only(query).strip()
    code = code.rstrip("; \t\r\n")  # a single trailing semicolon is fine

    if ";" in code:
        raise UnsafeSQLError("Only one SQL statement is allowed (found ';').")

    first_word = re.match(r"[a-zA-Z_]+", code)
    if not first_word or first_word.group(0).lower() not in _ALLOWED_START:
        raise UnsafeSQLError("Only SELECT queries (optionally starting with WITH) are allowed.")

    for word in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", code):
        if word.lower() in FORBIDDEN_KEYWORDS:
            raise UnsafeSQLError(f"Keyword '{word.upper()}' is not allowed; this database is read-only.")

    return query.strip().rstrip(";").rstrip()
