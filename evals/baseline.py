"""The single-prompt baseline the agent is compared against.

One-shot SQL: the model gets the whole schema up front, writes one query,
which runs once with no retries. A second call writes the answer from the
result. There is no tool loop and no discovery step.
"""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage, SystemMessage

from sql_agent import tools as db
from sql_agent.agent import _text

SQL_PROMPT = (
    "You write SQLite queries. Reply with exactly one read-only SELECT query "
    "inside a ```sql code block, and nothing else. Use only the tables and "
    "columns in the schema below."
)

ANSWER_PROMPT = (
    "Answer the user's question in plain English using only the query result. "
    "Give the key numbers and say briefly how you got them. If the result is an "
    "error, say the question could not be answered from the database."
)

_SQL_BLOCK = re.compile(r"```sql\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def full_schema() -> str:
    """Every table's columns, keys and sample rows, as one text block."""
    return "\n\n".join(db.describe_table(name) for name in db.list_tables())


def extract_sql(reply: str) -> str:
    """Pull the SQL out of a ```sql block, or use the whole reply if there is none."""
    match = _SQL_BLOCK.search(reply)
    return (match.group(1) if match else reply).strip().rstrip(";")


def ask_single_prompt(question: str, model) -> str:
    """Answer one question with one SQL attempt and no retries."""
    schema = full_schema()
    sql_reply = _text(model.invoke([
        SystemMessage(f"{SQL_PROMPT}\n\nSchema:\n{schema}"),
        HumanMessage(question),
    ]))
    sql = extract_sql(sql_reply)
    # A failed query is not retried. Its "ERROR: ..." text is passed to the answer call,
    # so the answer can report the failure.
    result = db.run_sql(sql).to_text()
    return _text(model.invoke([
        SystemMessage(ANSWER_PROMPT),
        HumanMessage(f"Question: {question}\n\nSQL:\n{sql}\n\nResult:\n{result}"),
    ]))
