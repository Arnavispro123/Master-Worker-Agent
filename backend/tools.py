"""Tools: files, shell (sandboxed), web, memory, reminders, open."""
from __future__ import annotations
import os
import sqlite3
import subprocess
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

WORKSPACE = Path(os.getenv("JARVIS_WORKSPACE", str(Path.home() / "Documents" / "Jarvis" / "workspace")))
WORKSPACE.mkdir(parents=True, exist_ok=True)
DB = WORKSPACE / "jarvis_memory.db"

BLOCKED_SHELL = ["rm -rf /", "rm -rf ~", ":(){", "format c:", "diskpart", "reg delete hklm",
                 "shutdown /s", "mkfs", "dd if="]

def _db():
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS memory (k TEXT PRIMARY KEY, v TEXT, ts TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, msg TEXT, due TEXT, done INT DEFAULT 0)")
    return c

# files
def file_read(path: str) -> str:
    p = (WORKSPACE / path).resolve() if not os.path.isabs(path) else Path(path)
    return p.read_text()[:20000]

def file_write(path: str, content: str) -> dict:
    p = (WORKSPACE / path).resolve() if not os.path.isabs(path) else Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return {"ok": True, "path": str(p)}

def file_list(path: str = ".") -> list[str]:
    p = (WORKSPACE / path).resolve() if not os.path.isabs(path) else Path(path)
    return [x.name for x in p.iterdir()][:200]

def resolve_special_dir(name: str) -> Path:
    """Desktop/Documents/Downloads — with OneDrive fallback on Windows."""
    home = Path.home()
    cands = [home / name, home / "OneDrive" / name]
    for c in cands:
        if c.exists():
            return c
    return home / name

def dir_make(path: str) -> dict:
    """Create a folder. Understands 'desktop', 'documents', 'downloads', ~ and absolute paths."""
    low = (path or "").strip().strip("'\"")
    if not low:
        return {"ok": False, "error": "no path given"}
    for special in ("desktop", "documents", "downloads"):
        if low.lower().startswith(special):
            rest = low[len(special):].lstrip("/\\ ")
            p = resolve_special_dir(special.capitalize()) / rest if rest else resolve_special_dir(special.capitalize())
            break
    else:
        p = Path(os.path.expanduser(low))
        if not p.is_absolute():
            p = WORKSPACE / low
    # models hallucinate usernames (C:\Users\user\Desktop\...): if the path
    # mentions Desktop but doesn't exist, remap onto the real Desktop
    import re as _re
    if not p.exists():
        m = _re.search(r"[Dd]esktop[/\\]*(.*)$", low)
        if m:
            p = resolve_special_dir("Desktop") / m.group(1).lstrip("/\\ ") if m.group(1) else resolve_special_dir("Desktop")
    try:
        p.mkdir(parents=True, exist_ok=False)
        return {"ok": True, "path": str(p)}
    except FileExistsError:
        return {"ok": True, "path": str(p), "note": "already existed"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}

def file_delete(path: str) -> dict:
    """Delete one file or EMPTY folder. Refuses home/root/workspace roots."""
    p = Path(os.path.expanduser((path or '').strip().strip('\'"')))
    if not p.is_absolute():
        p = WORKSPACE / str(path or '')
    try:
        rp = p.resolve()
        if rp in (Path.home(), WORKSPACE, Path.home() / "Desktop"):
            return {"ok": False, "error": "refusing to delete that folder"}
        if rp.is_dir():
            rp.rmdir()  # only empty dirs
        else:
            rp.unlink()
        return {"ok": True, "path": str(rp)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}

# shell
def shell_run(cmd: str, timeout: int = 30) -> dict:
    low = cmd.lower()
    for b in BLOCKED_SHELL:
        if b in low:
            return {"ok": False, "error": f"blocked dangerous command ({b})"}
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=str(WORKSPACE))
        out = (r.stdout + r.stderr)[-8000:]
        return {"ok": r.returncode == 0, "code": r.returncode, "output": out}
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}

# web
def web_search(query: str, n: int = 5) -> list[dict]:
    """Free DuckDuckGo instant answers + html fallback. No key needed."""
    import httpx
    try:
        r = httpx.get("https://api.duckduckgo.com/", params={"q": query, "format": "json", "no_html": 1}, timeout=20)
        d = r.json()
        out = []
        for t in (d.get("RelatedTopics") or [])[:n]:
            if isinstance(t, dict) and t.get("Text"):
                out.append({"title": t.get("Text", "")[:120], "url": t.get("FirstURL", "")})
        if d.get("AbstractText"):
            out.insert(0, {"title": d["AbstractText"][:200], "url": d.get("AbstractURL", "")})
        return out[:n] or [{"title": "No instant result — try opening a browser.", "url": ""}]
    except Exception as e:
        return [{"title": f"search failed: {e}", "url": ""}]

def url_fetch(url: str) -> str:
    import httpx
    r = httpx.get(url, timeout=25, follow_redirects=True, headers={"User-Agent": "JARVIS/1.0"})
    return r.text[:15000]

# memory
def remember(key: str, value: str) -> dict:
    c = _db()
    c.execute("INSERT OR REPLACE INTO memory VALUES (?,?,?)", (key, value, datetime.now().isoformat()))
    c.commit(); c.close()
    return {"ok": True}

def recall(key: str) -> str:
    c = _db()
    row = c.execute("SELECT v FROM memory WHERE k=?", (key,)).fetchone()
    c.close()
    return row[0] if row else ""

# reminders
def remind(msg: str, minutes: int = 10) -> dict:
    c = _db()
    due = (datetime.now() + timedelta(minutes=minutes)).isoformat()
    c.execute("INSERT INTO reminders (msg, due) VALUES (?,?)", (msg, due))
    c.commit(); c.close()
    return {"ok": True, "due": due}

# open
def open_target(target: str) -> dict:
    try:
        if target.startswith(("http://", "https://")):
            webbrowser.open(target)
            return {"ok": True}
        # windows apps
        if os.name == "nt" and not os.path.exists(target):
            os.startfile(target)  # type: ignore
        else:
            webbrowser.open(target)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
