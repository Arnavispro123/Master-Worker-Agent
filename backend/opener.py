"""Deterministic open/launch — works with zero AI.

"open youtube" must open YouTube even when every LLM is rate-limited
or too weak to emit a tool call. Pure intent matching, no model needed.
Site/app tables ported from the proven RandomStuffOpenCode/jarvis build.
"""
from __future__ import annotations
import re
import urllib.parse

from . import tools

SITES = {
    "google": "https://www.google.com", "youtube": "https://www.youtube.com",
    "wikipedia": "https://www.wikipedia.org", "github": "https://www.github.com",
    "stackoverflow": "https://www.stackoverflow.com", "reddit": "https://www.reddit.com",
    "twitter": "https://www.twitter.com", "x": "https://www.x.com",
    "facebook": "https://www.facebook.com", "instagram": "https://www.instagram.com",
    "linkedin": "https://www.linkedin.com", "netflix": "https://www.netflix.com",
    "amazon": "https://www.amazon.com", "spotify": "https://open.spotify.com",
    "discord": "https://www.discord.com", "twitch": "https://www.twitch.tv",
    "gmail": "https://mail.google.com", "outlook": "https://outlook.live.com",
    "maps": "https://maps.google.com", "translate": "https://translate.google.com",
    "chatgpt": "https://chat.openai.com", "claude": "https://claude.ai",
    "perplexity": "https://www.perplexity.ai", "whatsapp": "https://web.whatsapp.com",
}

APPS = {
    "notepad": "notepad.exe", "calculator": "calc.exe", "paint": "mspaint.exe",
    "word": "winword.exe", "excel": "excel.exe", "powerpoint": "powerpnt.exe",
    "cmd": "cmd.exe", "terminal": "wt.exe", "file explorer": "explorer.exe",
    "explorer": "explorer.exe", "task manager": "taskmgr.exe",
    "control panel": "control.exe", "settings": "ms-settings:",
    "snipping tool": "snippingtool.exe", "edge": "msedge.exe",
    "chrome": "chrome.exe", "firefox": "firefox.exe",
    "vscode": "code.exe", "visual studio code": "code.exe",
    "powershell": "powershell.exe",
}

_VERBS = ("open", "launch", "start", "go to", "take me to", "bring up")


def _clean_target(raw: str) -> str:
    t = (raw or "").strip().lower()
    t = re.sub(r"^(please\s+|can you\s+|could you\s+|would you\s+|kindly\s+)", "", t)
    t = re.sub(r"\s+(for me|please)\s*$", "", t).strip()
    return t


def try_open(message: str) -> dict | None:
    """If the message is an open/launch/play request, DO it. Returns result or None."""
    m = _clean_target(message or "")
    if len(m) > 120:
        return None

    # "play <x>" → YouTube search (your proven behavior)
    pm = re.match(r"^play\s+(.+)", m)
    if pm and len(pm.group(1)) > 1:
        q = pm.group(1).strip()
        tools.open_target(f"https://www.youtube.com/results?search_query={urllib.parse.quote(q)}")
        return {"text": f"Playing {q} on YouTube, sir.", "provider": "local", "model": "opener"}

    for v in _VERBS:
        if m.startswith(v + " ") or m == v:
            target = m[len(v):].strip() if m != v else ""
            if not target or target in ("it", "that", "this"):
                return {"text": "What should I open, sir?", "provider": "local", "model": "opener"}
            # "start a diet plan" is not an open request — leave it for the AI
            if v == "start" and target not in APPS and target not in SITES and " " in target:
                return None
            # app?
            if target in APPS:
                r = tools.open_target(APPS[target])
                ok = r.get("ok", False)
                return {"text": f"Opening {target}." if ok else f"Couldn't open {target}: {r.get('error', '?')}",
                        "provider": "local", "model": "opener"}
            # known site?
            if target in SITES:
                tools.open_target(SITES[target])
                return {"text": f"Opening {target}, sir.", "provider": "local", "model": "opener"}
            # raw url?
            if target.startswith(("http://", "https://", "www.")) or "." in target.replace(" ", ""):
                url = target if target.startswith("http") else f"https://{target}"
                tools.open_target(url)
                return {"text": f"Opening {url}.", "provider": "local", "model": "opener"}
            # fallback: app attempt, else google search
            r = tools.open_target(target)
            if r.get("ok"):
                return {"text": f"Opening {target}.", "provider": "local", "model": "opener"}
            tools.open_target(f"https://www.google.com/search?q={urllib.parse.quote(target)}")
            return {"text": f"I don't know {target} directly, so I searched Google for it.",
                    "provider": "local", "model": "opener"}
    return None
