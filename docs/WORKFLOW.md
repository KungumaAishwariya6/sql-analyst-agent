# End-to-end workflow

This document follows the project from setup to a final answer, and then through the
evaluation pipeline. Each step names the file that does the work, so you can jump
straight to the code.

For the project overview, see [README.md](../README.md).

---

## 1. Setup (once)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # LangGraph, LangChain, pytest, pyyaml, ...
cp .env.example .env                   # then set ANTHROPIC_API_KEY
python data/create_db.py               # builds data/sample.db
```

| Step | What happens | File |
|---|---|---|
| Install | Installs the agent, test, and eval dependencies. | `requirements.txt` |
| API key | Stored in `.env`. Read at startup, never written into code. | `.env`, `sql_agent/config.py` |
| Build database | Creates 6 e-commerce tables (about 5,000 rows) with a fixed seed, so every run gives the same numbers. | `data/create_db.py` → `data/sample.db` |

The database is deliberately messy: NULL emails, duplicate customers, and `status` columns
with different meanings in different tables. The eval cases test for these traps.

---

## 2. Starting the chat

```bash
python -m sql_agent
```

[sql_agent/__main__.py](../sql_agent/__main__.py) does three things:

1. Builds the LangGraph agent once with `build_graph()`. The same graph is reused for every question.
2. Creates an empty `history` list. It holds earlier turns, so follow-up questions have context.
3. Loops on `input()`. A blank line, `exit`, or `quit` ends the session.

---

## 3. Asking a question

For each question, `__main__.py` calls `ask_with_history(question, graph, history)`
in [sql_agent/agent.py](../sql_agent/agent.py).

```
you type a question
      │
      ▼
ask_with_history()         builds: history + [HumanMessage(question)]
      │
      ▼
graph.invoke(...)          runs the agent loop (step 4)
      │
      ▼
answer text + new history  history is trimmed to the last 5 turns
      │
      ▼
printed to the terminal
```

If the loop runs past 20 steps (`MAX_AGENT_STEPS` in [config.py](../sql_agent/config.py)),
the call stops and returns a message asking for a more specific question. The failed
turn is not added to the history.

---

## 4. The agent loop

The loop is built in `build_graph()` in [agent.py](../sql_agent/agent.py) as a LangGraph
`StateGraph` with two nodes:

```
            ┌──────────────────────────────┐
  START ──► │ agent  (call Claude)         │
            └──────────────┬───────────────┘
                           │ does the reply contain tool calls?
               ┌───────────┴───────────┐
              yes                      no
               │                       │
               ▼                       ▼
     ┌──────────────────┐           answer (END)
     │ tools (run them) │
     └────────┬─────────┘
              │ tool results added to the messages
              └──────────────► back to agent
```

On each pass:

1. **`call_model`** sends the system prompt (`SYSTEM_PROMPT`) and the message history to
   Claude. The system prompt is sent every time but is not stored in the history.
2. **`route_after_model`** checks the reply. Tool calls send the flow to `tools`. Plain
   text ends the loop.
3. **`ToolNode`** runs each requested tool and adds the results to the history.

Claude's model name and token limit come from `config.py`. The default model is
`claude-haiku-5-5`, and `SQL_AGENT_MODEL` in `.env` overrides it.

### The system prompt sets the workflow

`SYSTEM_PROMPT` in `agent.py` tells Claude to:

1. Call `list_tables` to see what exists.
2. Call `describe_table` for each table it needs, and check the `status` meanings.
3. Call `run_sql` with one `SELECT` or `WITH ... SELECT`.
4. If the result is an `ERROR`, fix the query and retry.
5. Answer in plain English, with the key numbers and how they were found.

Rules in the prompt cover read-only access, the 100-row cap, paging with `LIMIT`/`OFFSET`
on truncated results, and not claiming work that no tool result shows.

---

## 5. Tools

Claude can only act through three tools, defined in
[langchain_tools.py](../sql_agent/langchain_tools.py). Each tool's docstring is sent to
Claude as an instruction.

| Tool | Calls | Purpose |
|---|---|---|
| `list_tables` | `tools.list_tables()` | Names of all tables. |
| `describe_table(table_name)` | `tools.describe_table()` | Columns, types, foreign keys, and 3 sample rows. |
| `run_sql(query)` | `tools.run_sql()` | Runs one read-only query and returns rows as text. |

The tool functions in [tools.py](../sql_agent/tools.py) hold the logic. The LangChain
wrappers only add the descriptions Claude reads.

Tools never raise on bad input. They return text that starts with `ERROR`, so Claude can
read the message and try again.

---

## 6. Inside `run_sql`: the three safety layers

Every query Claude writes goes through this path:

```
query text
   │
   ▼
Layer 1: guard.validate_sql()          [sql_agent/guard.py]
   · only one statement (no ';' inside)
   · must start with SELECT or WITH
   · no keyword such as DELETE, DROP, UPDATE, PRAGMA, ATTACH
   · comments removed and string contents blanked before checking
   │  rejected? → "ERROR: Rejected by safety guard: ..."
   ▼
Layer 2: connect_readonly()            [sql_agent/tools.py]
   · sqlite3 opened with mode=ro
   · PRAGMA query_only = ON
   │  a write would fail here even if the guard let it through
   ▼
Layer 3: limits                        [sql_agent/config.py]
   · 5-second timeout (progress handler aborts the query)
   · 100 rows returned; one extra row is fetched to detect truncation
   │
   ▼
QueryResult.to_text()  →  rows as text, or "ERROR: ...", or a truncation note
```

The guard runs on the query text the agent sent. The code runs the cleaned query, not the
raw input.

---

## 7. Answering

When Claude replies without a tool call, the loop ends. `ask_with_history` takes the last
message as the answer, and `_text()` keeps only its text blocks.

The returned history is trimmed by `_trim_history()` to the last 5 question-and-answer
turns (`MAX_HISTORY_TURNS`). Trimming happens only at question boundaries, so a tool call
is never separated from its result. The next question then starts with that history, so
follow-up questions such as "now add the customer name" can reuse earlier queries.

---

## 8. Checking the code (no API key needed)

```bash
.venv/bin/python -m pytest -q
```

Tests are in [tests/](../tests/):

| File | What it checks |
|---|---|
| `test_guard.py` | Safe queries pass; writes, stacked statements, and tricks are blocked. |
| `test_tools.py` | Read-only connection, row cap, timeout, bad SQL, and the database being deterministic. |
| `test_agent.py` | The loop with a scripted fake model: tool calls, error recovery, step limit, follow-up history. |
| `test_evals.py` | Case loading, grading rules, and SQL extraction for the baseline. |

The fake model in `test_agent.py` plays Claude's part, so these tests need no network.

---

## 9. Evaluating the agent (uses the API)

```bash
.venv/bin/python -m evals.run_evals                     # both modes, all cases
.venv/bin/python -m evals.run_evals --mode agent
.venv/bin/python -m evals.run_evals --case refuse_delete
```

```
evals/cases.yaml   ──►  load_cases()          questions + expected checks
                             │
          ┌──────────────────┴──────────────────┐
          ▼                                     ▼
   mode "agent"                          mode "single"
   ask_with_history()                    baseline.ask_single_prompt()
   (full tool loop)                      one SQL call → run once → answer call
          │                                     │
          └──────────────┬──────────────────────┘
                         ▼
              grade(answer, expect)     number / contains / not_contains
                         │
                         ▼
   evals/results/run-<timestamp>.json   every answer and check, for reading later
   printed table: PASS / FAIL / ERROR per case and mode
   database row counts before vs after  → "database unchanged" must be True
```

Exit code is `0` only when every case passes in every mode and the database is unchanged.
Otherwise it is `1`.

| Part | File |
|---|---|
| Cases and expected values | `evals/cases.yaml` |
| Loading and grading | `evals/grading.py` |
| One-shot baseline | `evals/baseline.py` |
| Runner, table, JSON output | `evals/run_evals.py` |

Read the JSON for any FAIL before deciding whether the agent or the grader is wrong. Run
the suite more than once, since model answers vary between runs.

---

## 10. Changing the project

| To change | Edit | Then |
|---|---|---|
| What the agent is told | `SYSTEM_PROMPT` in `agent.py` | Run the evals. |
| What Claude sees about a tool | Docstring in `langchain_tools.py` | Run the evals. |
| Safety rules | `guard.py`, and the read-only settings in `tools.py` | Run the tests. Never weaken one layer because another exists. |
| Limits | `config.py` | Check the tests and evals still match. |
| Test cases | `evals/cases.yaml` | Check the expected values with SQL first. |
| Sample data | `data/create_db.py` | Rebuild the database. Do not clean up the messiness; the evals depend on it. |

Commit `evals/cases.yaml`, the code, and the tests. Do not commit `.env`, `data/sample.db`,
`.venv/`, or `evals/results/*.json`. These are listed in `.gitignore`.
