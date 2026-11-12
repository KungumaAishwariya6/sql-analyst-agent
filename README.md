# SQL Analyst Agent

Ask questions about a database in plain English. A LangGraph agent inspects the
schema, writes SQL, runs it read-only, recovers from its own errors, and answers.

Built with **LangGraph**, **LangChain**, **Claude** (via `langchain-anthropic`) and **SQLite**.

> **Status:** Days 1 and 2 are done (database, safety guard, tools, agent, CLI, tests).
> Day 3, the eval suite comparing a single prompt with the agent loop, is next.

## Why an agent and not a single prompt?

A single text-to-SQL call works for easy questions. An agent loop helps when the
first query isn't enough: it can discover the schema on demand, read a SQL error
and fix the query, and chain several queries for multi-step questions.

## How it works

```
question
   │
   ▼
┌─────────┐   tool call?   ┌─────────┐
│  agent  │ ─────yes─────► │  tools  │
│ (Claude)│ ◄──────────────│ (3 SQL  │
└─────────┘   tool result  │  tools) │
   │ no                    └────┬────┘
   ▼                            │ run_sql
 answer                         ▼
                        guard → read-only SQLite
```

1. The agent (`agent.py`) sends the question to Claude with a system prompt and three tools.
2. Claude calls `list_tables` and `describe_table` to learn the schema, then writes SQL and calls `run_sql`.
3. `run_sql` checks the query with the guard. Approved queries run on a read-only connection, with row and time limits.
4. Results, or error text, go back to Claude. On an error, Claude fixes the query and retries.
5. When Claude has enough information it answers. If it passes 20 graph steps, the agent stops and says so.

## Project layout

```
sql_agent/agent.py              LangGraph loop (agent <-> tools), system prompt, ask()
sql_agent/langchain_tools.py    LangChain wrappers; their docstrings are prompts for the model
sql_agent/tools.py              list_tables, describe_table, run_sql (plain Python, the security boundary)
sql_agent/guard.py              SQL safety validator
sql_agent/config.py             paths, limits, model name, .env loading
sql_agent/__main__.py           interactive chat (python -m sql_agent)
data/create_db.py               generates the sample e-commerce SQLite database
tests/                          pytest suite (guard, tools, agent with a scripted fake model)
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python data/create_db.py          # build data/sample.db
pytest                            # 52 tests, no API key needed

cp .env.example .env              # then set ANTHROPIC_API_KEY in .env
python -m sql_agent               # interactive chat
```

Get an API key from https://console.anthropic.com (Settings → API Keys). Set
`SQL_AGENT_MODEL` in `.env` to change the model. The default is `claude-haiku-5-5`.

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
3. **Limits**: results capped at 100 rows, queries aborted after 5 seconds, and at
   most 20 agent steps per question.

Tool errors are returned as text, not raised, so the agent can read them and retry.
Tests cover each layer.

## Design decisions

- **Tools are plain functions, wrapped separately.** The safety logic is tested without the LLM. The LangChain layer only adds descriptions.
- **Tool docstrings are prompts.** The model reads them, so they are written as instructions.
- **The schema is discovered, not hard-coded.** The agent calls `list_tables` and `describe_table` at runtime. This is tested only on the sample database.
- **Messy data is intentional.** A clean schema would not test whether the agent handles ambiguity.
