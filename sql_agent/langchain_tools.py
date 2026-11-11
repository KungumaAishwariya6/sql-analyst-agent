"""LangChain tool wrappers around the plain functions in tools.py.

The model sees these tools: their names, docstrings and argument types are sent
to Claude, so the docstrings are instructions for the model, not just notes
for developers.
"""

from langchain_core.tools import tool

from sql_agent import tools as db


@tool("list_tables")
def list_tables_tool() -> str:
    """List the names of all tables in the database. Call this first."""
    try:
        return "\n".join(db.list_tables())
    except FileNotFoundError as exc:
        return f"ERROR: {exc}"


@tool("describe_table")
def describe_table_tool(table_name: str) -> str:
    """Show the columns, types, foreign keys and sample rows of one table."""
    try:
        return db.describe_table(table_name)
    except FileNotFoundError as exc:
        return f"ERROR: {exc}"


@tool("run_sql")
def run_sql_tool(query: str) -> str:
    """Run one read-only SELECT query and return the rows as text.

    Errors (including safety-guard rejections) are returned as text starting
    with 'ERROR', so read the message, fix the query and try again.
    """
    return db.run_sql(query).to_text()


# The complete list of tools the agent is allowed to call.
AGENT_TOOLS = [list_tables_tool, describe_table_tool, run_sql_tool]
