# CLAUDE.md

Instructions for working in this repo. For the project overview, see README.md.

## Commands

- Use `.venv/bin/python` for everything, not the system `python`.
- Tests: `.venv/bin/python -m pytest -q` (no API key needed).
- Build the sample DB: `.venv/bin/python data/create_db.py`.
- Run the agent: `.venv/bin/python -m sql_agent` (needs `ANTHROPIC_API_KEY` in `.env`).

## Rules

- Keep all three safety layers: the guard in `sql_agent/guard.py`, the read-only connection in `sql_agent/tools.py`, and the row and time limits. Don't weaken one because another exists.
- Tools return error text instead of raising, so the agent can read the error and retry.
- Tool docstrings in `sql_agent/langchain_tools.py` are prompts for the model. Edit them with that in mind.
- Don't clean up the sample data in `data/create_db.py`. The mess is what tests the agent.
- Never commit `.env`, `data/sample.db` or `.venv/`. All are in `.gitignore`.
- Day 3 (evals in `evals/`, using `pyyaml`) is not built yet.
