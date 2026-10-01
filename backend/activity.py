"""Activity bus — one place every UI action is announced.

The orb (and any HUD) polls this, so the orb reacts no matter which window
acted: Electron HUD, browser tab, or headless backend. Electron IPC stays as
a fast lane for voice levels; everything else flows through here.
"""
from __future__ import annotations
import threading
import time

_lock = threading.Lock()
_events: list[dict] = []
_next_id = 1
_KEEP = 50


def push(kind: str, text: str = "") -> dict | None:
    """Levels are IPC-only (too chatty); everything else is stored."""
    global _next_id
    if (kind or "") == "level":
        return None
    with _lock:
        e = {"id": _next_id, "kind": kind or "idle",
             "text": (text or "")[:160], "t": time.time()}
        _next_id += 1
        _events.append(e)
        del _events[:-_KEEP]
        return e


def poll(since: int = 0) -> list[dict]:
    with _lock:
        return [e for e in _events if e["id"] > since][-20:]


def latest() -> dict | None:
    with _lock:
        return _events[-1] if _events else None
