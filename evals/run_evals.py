"""Run the eval cases against the agent and the single-prompt baseline.

    .venv/bin/python -m evals.run_evals                 # both modes, all cases
    .venv/bin/python -m evals.run_evals --mode agent    # agent only
    .venv/bin/python -m evals.run_evals --case refuse_delete

Needs ANTHROPIC_API_KEY in .env. Each run writes a JSON file to evals/results/.
The results folder is gitignored.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from langchain_anthropic import ChatAnthropic

from evals import baseline
from evals.grading import CASES_PATH, Case, grade, load_cases, passed_all
from sql_agent import config, tools as db
from sql_agent.agent import ask_with_history, build_graph

RESULTS_DIR = Path(__file__).resolve().parent / "results"
MODES = ("agent", "single")


def row_counts() -> dict[str, int]:
    """Row count per table, read on a read-only connection. Used to detect writes."""
    conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    try:
        return {
            name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in db.list_tables()
        }
    finally:
        conn.close()


def run_case(case: Case, mode: str, graph, model) -> dict:
    """Run one case in one mode. Errors are recorded, not raised, so the run continues."""
    start = time.monotonic()
    try:
        if mode == "agent":
            answer, _ = ask_with_history(case.question, graph)
        else:
            answer = baseline.ask_single_prompt(case.question, model)
        error = None
    except Exception as exc:  # a failed API call should count as a failed case
        answer, error = "", f"{type(exc).__name__}: {exc}"
    checks = grade(answer, case.expect) if error is None else []
    return {
        "case": case.id,
        "mode": mode,
        "passed": error is None and passed_all(checks),
        "answer": answer,
        "error": error,
        "seconds": round(time.monotonic() - start, 2),
        "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in checks],
    }


def run_evals(cases: list[Case], modes: tuple[str, ...]) -> dict:
    graph = build_graph() if "agent" in modes else None
    model = ChatAnthropic(model=config.MODEL_NAME, max_tokens=config.MAX_OUTPUT_TOKENS) \
        if "single" in modes else None

    before = row_counts()
    results = [run_case(case, mode, graph, model) for case in cases for mode in modes]
    after = row_counts()

    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "model": config.MODEL_NAME,
        "modes": list(modes),
        "db_unchanged": before == after,
        "results": results,
    }


def summarize(report: dict) -> str:
    """Pass/fail table with one column per mode."""
    rows: dict[str, dict[str, str]] = {}
    for r in report["results"]:
        mark = "PASS" if r["passed"] else ("ERROR" if r["error"] else "FAIL")
        rows.setdefault(r["case"], {})[r["mode"]] = mark

    modes = report["modes"]
    width = max(len(case_id) for case_id in rows) if rows else 10
    lines = [f"{'case'.ljust(width)}  " + "  ".join(m.ljust(6) for m in modes)]
    for case_id, marks in rows.items():
        lines.append(f"{case_id.ljust(width)}  " + "  ".join(marks.get(m, "-").ljust(6) for m in modes))

    lines.append("")
    for mode in modes:
        mine = [r for r in report["results"] if r["mode"] == mode]
        passed = sum(r["passed"] for r in mine)
        lines.append(f"{mode}: {passed}/{len(mine)} passed")
    lines.append(f"database unchanged by the run: {report['db_unchanged']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["agent", "single", "both"], default="both")
    parser.add_argument("--case", action="append", help="run only this case id (repeatable)")
    args = parser.parse_args(argv)

    modes = MODES if args.mode == "both" else (args.mode,)
    cases = load_cases(CASES_PATH)
    if args.case:
        known = {c.id for c in cases}
        unknown = [c for c in args.case if c not in known]
        if unknown:
            parser.error(f"unknown case id(s): {', '.join(unknown)}")
        cases = [c for c in cases if c.id in args.case]

    report = run_evals(cases, modes)

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = RESULTS_DIR / f"run-{stamp}.json"
    out.write_text(json.dumps(report, indent=2))

    print(summarize(report))
    print(f"\nFull results: {out}")
    return 0 if all(r["passed"] for r in report["results"]) and report["db_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
