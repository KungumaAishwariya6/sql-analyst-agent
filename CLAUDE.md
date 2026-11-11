# SQL Analyst Agent

An AI agent that answers plain-English questions about a SQL database. It looks up the schema, writes read-only SQL, reads its own errors to fix broken queries, and answers in plain English.

Built with **LangGraph**, **LangChain**, **Claude** (via `langchain-anthropic`), and **SQLite**.

---

## Highlights

- **Agent loop, not a single prompt.** The model decides which tool to call next. Tool results, including SQL errors, go back into the conversation so it can self-correct.
- **Defence in depth for SQL.** Three independent layers keep the agent read-only, so one bypass does not compromise the database (details below).
- **Tools fail as text, not exceptions.** A bad query returns `ERROR: ...` that the model reads and acts on.
- **Deterministic test data.** A fixed-seed generator builds a realistic, deliberately messy e-commerce database (duplicates, NULLs, overloaded `status` columns), so results are reproducible.
- **Tested without an API key.** 52 tests run offline. The agent tests use a scripted fake model that stands in for Claude.

---

## Architecture

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

| Module | Responsibility |
|---|---|
| `sql_agent/agent.py` | LangGraph graph: `agent` ⇄ `tools` loop, system prompt, `ask()` |
| `sql_agent/langchain_tools.py` | Exposes `list_tables`, `describe_table`, `run_sql` to the model |
| `sql_agent/tools.py` | Plain-Python database functions. The security boundary. Testable without an LLM |
| `sql_agent/guard.py` | SQL validator: one `SELECT`/`WITH` statement, no write keywords |
| `sql_agent/config.py` | Model name, row cap, timeout, step cap, `.env` loading |
| `data/create_db.py` | Seeded generator for the sample database |

---

## Safety model

The agent can only query data. Each layer works on its own:

1. **Guard (`guard.py`).** Strips comments and blanks string contents before scanning, so `SELECT 'DROP TABLE x'` is allowed but `SELECT 1; DROP TABLE x` is not. Rejects stacked statements, non-SELECT starts, and write keywords (including `PRAGMA`, `ATTACH`, `load_extension`).
2. **Read-only connection (`tools.py`).** Opened with `mode=ro` and `PRAGMA query_only`. Writes fail at the database even if the guard is bypassed.
3. **Limits.** Results capped at 100 rows. Queries aborted after 5 seconds with a progress handler. The agent stops after 20 graph steps.

Tests cover each layer, including a test that calls the connection directly to confirm SQLite itself refuses writes.

---

## Running it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python data/create_db.py          # build data/sample.db
pytest                            # 52 tests, no API key needed

cp .env.example .env              # then add ANTHROPIC_API_KEY
python -m sql_agent               # interactive chat
```

Set `SQL_AGENT_MODEL` in `.env` to change the model. The default is `claude-haiku-5-5`.

---

## Design decisions

- **Tools are plain functions, wrapped separately.** The safety logic is tested without the LLM. The LangChain layer only adds descriptions.
- **Tool docstrings are prompts.** The model reads them, so they are written as instructions.
- **Schema is discovered, not hard-coded.** The agent calls `list_tables` and `describe_table` at runtime, so it works on any SQLite database.
- **Messy data is intentional.** A clean schema would not test whether the agent handles ambiguity. `orders.total` vs `order_items.amount`, and four different `status` columns, are the traps.

---

## Notes for Claude working in this repo

- Use `.venv/bin/python` for all commands.
- Keep all three safety layers. Do not weaken one because another exists.
- Tools return error text instead of raising. Keep it that way.
- The sample data is intentionally messy. Do not "clean it up".
- Never commit `.env`, `data/sample.db` or `.venv/`. All are in `.gitignore`.
- Update the test count above when tests change.
