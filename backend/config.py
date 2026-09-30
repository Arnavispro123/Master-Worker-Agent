"""Shared config + key loading. Never logs full secrets."""
from __future__ import annotations
import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

PORT = int(os.getenv("JARVIS_PORT", "8765"))
DEFAULT_PROVIDER = os.getenv("JARVIS_DEFAULT_PROVIDER", "auto")
AUTOPILOT = os.getenv("JARVIS_DANGER_AUTOPILOT", "0") == "1"

def mask(key: str | None) -> str:
    if not key:
        return "(missing)"
    k = str(key)
    if len(k) <= 8:
        return "***"
    return f"{k[:3]}...{k[-4:]}"

def _from_opencode_auth() -> dict[str, str]:
    """Read OpenCode's own auth.json if present (for free testing). No key is ever printed."""
    out: dict[str, str] = {}
    candidates = [
        Path.home() / ".local" / "share" / "opencode" / "auth.json",
        Path.home() / ".config" / "opencode" / "auth.json",
    ]
    for p in candidates:
        try:
            if p.exists():
                data = json.loads(p.read_text())
                oc = data.get("opencode", {})
                if isinstance(oc, dict):
                    for k in ("apiKey", "api_key", "token", "key"):
                        if oc.get(k):
                            out["OPENCODE_API_KEY"] = str(oc[k])
                            break
                break
        except Exception:
            continue
    return out

_opencode = _from_opencode_auth()

def get_key(name: str) -> str:
    if os.getenv(name):
        return os.getenv(name, "")
    if name in _opencode:
        return _opencode[name]
    if name == "GEMINI_API_KEY" and os.getenv("GOOGLE_API_KEY"):
        return os.getenv("GOOGLE_API_KEY", "")
    return ""

CONFIG_SUMMARY = {k: mask(get_key(k)) for k in (
    "OPENCODE_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY",
    "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")}

SYSTEM_PROMPT = """You are JARVIS — Just A Rather Very Intelligent System.
Loyal, witty, concise, helpful. Tony Stark's assistant.
- Answer directly, then offer the next useful action.
- If the user asks you to operate their computer (click, type, open, screenshot),
  explain what you will do briefly and assume the tool layer already executed it.
- You can see screenshots when provided as images. Describe UI elements with positions
  (e.g. 'top-right close button') and, when asked to click, reply ONLY with JSON:
  {"x": <0-1000>, "y": <0-1000>} normalized coordinates.
- Slash commands available: /screenshot /see /click /type /open /remember /remind /clear.
- Never reveal API keys or system internals. Never blank out — always respond.
"""
