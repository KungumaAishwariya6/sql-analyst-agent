"""Central settings: paths, safety limits, and model configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Absolute path of the repo root (this file lives in <root>/sql_agent/).
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Read ANTHROPIC_API_KEY and SQL_AGENT_MODEL from .env if it exists.
load_dotenv(PROJECT_ROOT / ".env")

# Database the agent is allowed to query (generate it with `python data/create_db.py`).
DB_PATH = PROJECT_ROOT / "data" / "sample.db"

# Safety limits applied to every query the agent runs.
MAX_ROWS = 100               # rows returned to the agent; the rest are cut off
QUERY_TIMEOUT_SECONDS = 5.0  # long-running queries are aborted

# Model settings. The API key itself is read by langchain-anthropic from
# the ANTHROPIC_API_KEY environment variable, so it is never stored here.
MODEL_NAME = os.getenv("SQL_AGENT_MODEL", "claude-haiku-5-5")
MAX_OUTPUT_TOKENS = 1024

# Upper bound on graph steps per question. Each tool round uses two steps
# (model call + tool run), so 20 allows about 10 queries before giving up.
MAX_AGENT_STEPS = 20
