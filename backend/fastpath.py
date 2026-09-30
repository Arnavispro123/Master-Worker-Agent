"""Local fast-path: clock/date questions answered instantly, no LLM, no rate limits.

"what time is it" should never cost 6 agent steps + a 429.
"""
from __future__ import annotations
import re
from datetime import datetime

_PATTERNS = [
    (re.compile(r"\b(what'?s the time|what time is it|current time|tell me the time|time right now|time now)\b"), "time"),
    (re.compile(r"\b(what'?s (the |today'?s )?date|what day is it|what day is today|today'?s date|current date)\b"), "date"),
    (re.compile(r"\b(what time and date|current date and time|what'?s today)\b"), "both"),
]


def try_fastpath(message: str) -> dict | None:
    m = (message or "").strip().lower()
    if len(m) > 140:
        return None
    kind = None
    for rx, k in _PATTERNS:
        if rx.search(m):
            kind = k
            break
    if not kind:
        return None
    now = datetime.now().astimezone()
    if kind == "time":
        text = f"It's {now.strftime('%A, %B %d, %Y — %I:%M:%S %p (%Z)')} locally, sir."
    elif kind == "date":
        text = f"Today is {now.strftime('%A, %B %d, %Y')}, sir."
    else:
        text = f"It's {now.strftime('%A, %B %d, %Y — %I:%M %p (%Z)')} locally, sir."
    return {"text": text, "provider": "local", "model": "clock"}
