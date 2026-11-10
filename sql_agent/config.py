"""Central settings. Day 2 adds the model name and API key handling."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Database the agent is allowed to query (generate it with `python data/create_db.py`).
DB_PATH = PROJECT_ROOT / "data" / "sample.db"

# Safety limits applied to every query the agent runs.
MAX_ROWS = 100               # rows returned to the agent; the rest are cut off
QUERY_TIMEOUT_SECONDS = 5.0  # long-running queries are aborted
