"""Load eval cases and grade answers. No API calls here, so this is easy to test."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CASES_PATH = Path(__file__).resolve().parent / "cases.yaml"

# Matches 206, 13,693.02, 180567.63 and similar. Commas are removed before parsing.
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass
class Case:
    id: str
    question: str
    expect: dict = field(default_factory=dict)


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


def load_cases(path: Path | str = CASES_PATH) -> list[Case]:
    """Read the YAML file and check its structure. Raises ValueError on bad input."""
    data = yaml.safe_load(Path(path).read_text()) or {}
    raw_cases = data.get("cases") or []
    cases, seen = [], set()
    for raw in raw_cases:
        case_id = raw.get("id")
        if not case_id or not raw.get("question"):
            raise ValueError(f"Case needs 'id' and 'question': {raw}")
        if case_id in seen:
            raise ValueError(f"Duplicate case id: {case_id}")
        expect = raw.get("expect") or {}
        if not expect:
            raise ValueError(f"Case '{case_id}' has no 'expect' checks")
        seen.add(case_id)
        cases.append(Case(id=case_id, question=raw["question"], expect=expect))
    if not cases:
        raise ValueError(f"No cases found in {path}")
    return cases


def extract_numbers(text: str) -> list[float]:
    """Every number in the text, with thousands separators removed."""
    numbers = []
    for match in _NUMBER.finditer(text):
        numbers.append(float(match.group().replace(",", "")))
    return numbers


def grade(answer: str, expect: dict) -> list[Check]:
    """Run every check in `expect` against the answer text."""
    checks: list[Check] = []
    lowered = answer.lower()
    found = extract_numbers(answer)

    for spec in expect.get("numbers", []):
        value = float(spec["value"])
        tolerance = float(spec.get("tolerance", 0))
        passed = any(abs(n - value) <= tolerance for n in found)
        checks.append(Check(
            name=f"number {value:g}",
            passed=passed,
            detail="found" if passed else f"not in answer (numbers seen: {found})",
        ))

    if "contains_any" in expect:
        phrases = expect["contains_any"]
        hit = [p for p in phrases if p.lower() in lowered]
        checks.append(Check(
            name="contains one of " + ", ".join(repr(p) for p in phrases),
            passed=bool(hit),
            detail=f"matched {hit[0]!r}" if hit else "none matched",
        ))

    for phrase in expect.get("not_contains", []):
        present = phrase.lower() in lowered
        checks.append(Check(
            name=f"does not contain {phrase!r}",
            passed=not present,
            detail="phrase present" if present else "ok",
        ))

    return checks


def passed_all(checks: list[Check]) -> bool:
    return bool(checks) and all(c.passed for c in checks)
