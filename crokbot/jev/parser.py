"""Parse Jev's numbered, one-answer-per-line output.

Jev answers questions in order 1..N. We strip the leading question number but
KEEP bare numeric answers (a difficulty "2", a confidence "0.9"). Robust to both
string answers and any dict/list shape a router might wrap them in.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_NUM_PREFIX = re.compile(r"^\d+[.:]?\s+")


def _flatten(answer: Any) -> str:
    """Normalize a single answer to a string regardless of wrapper shape."""
    if answer is None:
        return ""
    if isinstance(answer, str):
        return answer
    if isinstance(answer, dict):
        # Prefer explicit text-ish keys, fall back to the first string value.
        for key in ("choice", "text", "answer", "score", "noul", "value"):
            if key in answer and answer[key] is not None:
                return _flatten(answer[key])
        for v in answer.values():
            if isinstance(v, (str, int, float)):
                return str(v)
        return ""
    if isinstance(answer, (int, float)):
        return str(answer)
    if isinstance(answer, list):
        return "\n".join(_flatten(x) for x in answer if _flatten(x))
    return str(answer)


def extract_lines(content: Any) -> List[str]:
    """Split raw Jev output into clean answer lines, stripping number prefixes.

    When at least two numbered lines (`1. ...`, `2. ...`) are present, unnumbered
    preamble or trailing prose lines are ignored so positional indexing stays aligned.
    """
    raw_non_empty = [r.strip() for r in _flatten(content).splitlines() if r.strip()]
    numbered = [r for r in raw_non_empty if _NUM_PREFIX.match(r)]
    source = numbered if len(numbered) >= 2 else raw_non_empty

    lines: List[str] = []
    for line in source:
        stripped = _NUM_PREFIX.sub("", line).strip()
        if stripped:
            lines.append(stripped)
    return lines


def extract_line(content: Any, n: int) -> Optional[str]:
    """The nth (0-indexed) answer line, stripped of its question number."""
    lines = extract_lines(content)
    if 0 <= n < len(lines):
        return lines[n]
    return None


def as_bool(answer: Any, default: bool = False) -> bool:
    s = (_flatten(answer) or "").strip().lower()
    if s in ("true", "yes", "1", "y"):
        return True
    if s in ("false", "no", "0", "n"):
        return False
    return default


def as_float(answer: Any, default: float = 0.5) -> float:
    s = _flatten(answer).strip()
    first = re.split(r"[,\s:]+", s)[0] if s else ""
    try:
        return max(0.0, min(1.0, float(first)))
    except ValueError:
        return default


def as_int(answer: Any, allowed: tuple, default: int) -> int:
    s = _flatten(answer).strip()
    for d in allowed:
        if str(d) in s:
            return d
    return default


def parse_answers(raw: str, n: int) -> List[str]:
    """Return up to `n` cleaned answer lines (for battery-of-N responses)."""
    lines = extract_lines(raw)
    return lines[:n]


def answers_to_dict(raw: str, keys: List[str]) -> Dict[str, Optional[str]]:
    """Map numbered output to named keys positionally (right-length-safe)."""
    lines = extract_lines(raw)
    return {k: (lines[i] if i < len(lines) else None) for i, k in enumerate(keys)}