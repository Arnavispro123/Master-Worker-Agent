"""User preferences cache — provider/model/switches/TTS, saved to disk.

Survives restarts. Never stores API keys (those stay in .env).
File: <repo>/preferences.json (gitignored).
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREFS_FILE = ROOT / "preferences.json"

DEFAULTS = {
    "provider": "auto",
    "model": "",
    "autopilot": False,
    "agent_mode": False,
    "voice_on": True,
    "wake_on": False,
    "tts_voice": "en-GB-RyanNeural",
    "tts_rate": "+25%",
}

_BOOL_KEYS = {"autopilot", "agent_mode", "voice_on", "wake_on"}
_STR_KEYS = {"provider", "model", "tts_voice", "tts_rate"}


def load() -> dict:
    prefs = dict(DEFAULTS)
    try:
        if PREFS_FILE.exists():
            data = json.loads(PREFS_FILE.read_text())
            if isinstance(data, dict):
                for k in _BOOL_KEYS:
                    if k in data:
                        prefs[k] = bool(data[k])
                for k in _STR_KEYS:
                    if k in data and isinstance(data[k], str):
                        prefs[k] = data[k][:120]
    except Exception:
        pass
    return prefs


def save(patch: dict) -> dict:
    prefs = load()
    for k in _BOOL_KEYS:
        if k in patch:
            prefs[k] = bool(patch[k])
    for k in _STR_KEYS:
        if k in patch and isinstance(patch[k], str):
            prefs[k] = patch[k][:120]
    try:
        PREFS_FILE.write_text(json.dumps(prefs, indent=2))
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    return {"ok": True, "prefs": prefs}
