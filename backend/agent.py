"""JARVIS agent loop — thinks, picks tools, executes, repeats. No API keys needed for plumbing."""
from __future__ import annotations
import json
import re
from typing import Optional

from . import providers, tools
from . import vision_control as vc

TOOL_MANIFEST = """You control this computer via JSON tool calls. You have FULL autonomy already — never ask the user for confirmation, just act. Reply with EITHER:
1) a final answer: FINAL: <text>, OR
2) tool calls fenced as ```json [ {"tool": name, "args": {...}} ] ```
STRICT FORMAT: one tool = one {...} object. Multiple tools = separate objects in ONE [...] array or SEPARATE fenced blocks. NEVER merge two tools into one object (no duplicate "tool" keys). NEVER paste tool JSON outside a fenced block. Example:
```json [{"tool": "shell", "args": {"cmd": "dir"}}]```
Simple questions (time, date, greetings) need NO tools — answer FINAL directly.
Available tools (args in one object):
- shell {cmd}: run terminal command (sandboxed, blocked list enforced)
- file_read {path}, file_write {path, content}, file_list {path}
- dir_make {path}: create a folder ("desktop/hello" works, OneDrive-aware)
- file_delete {path}: delete one file or EMPTY folder (guarded)
- web_search {q}, url_fetch {url}
- research {q}: full research — searches the web, reads pages, answers with sources
- remember {key, value}, recall {key}, remind {msg, minutes}
- open {target}: open URL or app name
- screenshot {}: returns [image attached]
- see {question}: look at screen now
- click {x, y} (0-1000 normalized) | click_target {instruction} | type {text} | press {key} | scroll {amount}
ONLY these exact tool names exist. There is NO file_create, file_rename, explorer, browser or terminal tool — use file_write, shell, open instead.
Rules: max 1-3 calls per turn. Prefer shell/file/web over UI control. Never invent file contents you haven't read.
Research-then-save tasks: research {q} first, then dir_make, then file_write with the findings."""

def _split_objects(s: str) -> list[str]:
    """Split concatenated {...}{...} into balanced top-level objects (string-aware)."""
    objs: list[str] = []
    depth = 0
    start = -1
    instr = False
    esc = False
    for i, ch in enumerate(s):
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
        else:
            if ch == '"':
                instr = True
            elif ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start != -1:
                    objs.append(s[start:i + 1])
                    start = -1
    return objs

def _extract_calls(text: str) -> list[dict]:
    calls: list[dict] = []
    for m in re.finditer(r"```json(.*?)```", text, re.S | re.I):
        block = m.group(1).strip()
        try:
            data = json.loads(block)
            items = data if isinstance(data, list) else [data]
            for d in items:
                if isinstance(d, dict) and d.get("tool"):
                    calls.append(d)
            if calls:
                continue
        except Exception:
            pass
        # fallback: concatenated objects, or one object with merged duplicate keys
        for obj in _split_objects(block):
            try:
                d = json.loads(obj)
                if isinstance(d, dict) and d.get("tool"):
                    calls.append(d)
            except Exception:
                continue
    # bare {"tool": ...} fallback (unfenced)
    if not calls:
        for obj in _split_objects(text):
            try:
                d = json.loads(obj)
                if isinstance(d, dict) and d.get("tool"):
                    calls.append(d)
                    if len(calls) >= 3:
                        break
            except Exception:
                continue
    # weak-model prose shapes: research('x') and "1. file_write 'path'"
    if not calls:
        calls = _extract_prose_calls(text)
    return calls[:3]


# positional-arg order per tool for prose-style calls
_PROSE_ARGS: dict[str, list[str]] = {
    "research": ["q"], "web_search": ["q"], "url_fetch": ["url"],
    "file_read": ["path"], "file_write": ["path", "content"],
    "file_list": ["path"], "dir_make": ["path"], "file_delete": ["path"],
    "shell": ["cmd"], "open": ["target"], "recall": ["key"],
    "remember": ["key", "value"], "remind": ["msg", "minutes"],
    "see": ["question"], "click_target": ["instruction"],
    "type": ["text"], "press": ["key"], "scroll": ["amount"],
    "screenshot": [],
}
_KNOWN_TOOLS = set(_PROSE_ARGS) | {"click"}


def _split_quoted(s: str) -> list[str]:
    """Split 'a', "b", c on commas, respecting quotes."""
    parts, cur, q = [], "", None
    for ch in s:
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in ("'", '"'):
            q = ch
            cur += ch
        elif ch == ",":
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    out = []
    for p in parts:
        p = p.strip()
        if len(p) >= 2 and p[0] == p[-1] and p[0] in ("'", '"'):
            p = p[1:-1]
        out.append(p)
    return out


def _extract_prose_calls(text: str) -> list[dict]:
    calls: list[dict] = []
    # 1) call syntax: research('x'), dir_make("y"), file_write('p', 'c')
    for m in re.finditer(r"\b([a-z_]+)\s*\(([^()]*)\)", text):
        name = m.group(1)
        if name not in _KNOWN_TOOLS or name == "click":
            continue
        keys = _PROSE_ARGS.get(name, [])
        vals = _split_quoted(m.group(2))
        if not vals:
            continue
        args = {k: v for k, v in zip(keys, vals)}
        if name == "click" or not args:
            continue
        # skip placeholders like "research output"
        if any("research output" in str(v).lower() for v in args.values()):
            continue
        calls.append({"tool": name, "args": args})
        if len(calls) >= 3:
            return calls
    # 2) numbered list: 1. file_write 'C:\x'  2. research 'y'
    for m in re.finditer(r"(?m)^\s*\d+[.)]\s*([a-z_]+)\s+(['\"])(.+?)\2", text):
        name = m.group(1)
        if name not in _KNOWN_TOOLS or name in ("click", "file_write"):
            continue
        keys = _PROSE_ARGS.get(name, [])
        if not keys:
            continue
        calls.append({"tool": name, "args": {keys[0]: m.group(3).strip()}})
        if len(calls) >= 3:
            break
    return calls


# reads/research first so later writes can use their output
_READ_FIRST = {"research", "web_search", "url_fetch", "recall", "file_read",
               "file_list", "screenshot", "see"}


def _order_calls(calls: list[dict]) -> list[dict]:
    return sorted(calls, key=lambda c: 0 if str(c.get("tool", "")) in _READ_FIRST else 1)

async def _run_tool(name: str, args: dict, autopilot: bool) -> dict:
    try:
        if name == "research":
            from . import research as research_mod
            return await research_mod.research(str(args.get("q", ""))[:300])
        if name == "shell":
            return tools.shell_run(str(args.get("cmd", ""))[:2000])
        if name == "file_read":
            return {"output": tools.file_read(str(args.get("path", "")))[:6000]}
        if name == "file_write":
            return tools.file_write(str(args.get("path", "")), str(args.get("content", ""))[:50000])
        if name == "file_list":
            return {"files": tools.file_list(str(args.get("path", ".")))}
        if name == "dir_make":
            return tools.dir_make(str(args.get("path", "")))
        if name == "file_delete":
            return tools.file_delete(str(args.get("path", "")))
        if name == "web_search":
            return {"results": tools.web_search(str(args.get("q", "")))[:6]}
        if name == "url_fetch":
            return {"output": tools.url_fetch(str(args.get("url", "")))[:6000]}
        if name == "remember":
            return tools.remember(str(args.get("key", "note")), str(args.get("value", "")))
        if name == "recall":
            return {"output": tools.recall(str(args.get("key", "")))}
        if name == "remind":
            return tools.remind(str(args.get("msg", "")), int(args.get("minutes", 10)))
        if name == "open":
            return tools.open_target(str(args.get("target", "")))
        if name == "screenshot":
            s = vc.take_screenshot()
            return {"ok": True, "w": s["w"], "h": s["h"], "_image": s["image_b64"][:100] + "...(attached)"}
        if name == "see":
            return {"note": "screenshot attached next turn; describe it"}
        if name == "click":
            return vc.click(args.get("x"), args.get("y"), confirm=True, autopilot=True)
        if name == "click_target":
            xy = None
            return {"note": "use see first, then click with x/y", "instruction": args.get("instruction", "")}
        if name == "type":
            return vc.type_text(str(args.get("text", ""))[:1000], confirm=True, autopilot=True)
        if name == "press":
            return vc.press(str(args.get("key", "enter")))
        if name == "scroll":
            return vc.scroll(int(args.get("amount", 3)))
        return {"error": f"unknown tool {name}"}
    except Exception as e:
        return {"error": str(e)[:300]}

async def run_goal(goal: str, provider: str = "auto", model: Optional[str] = None,
                   max_steps: int = 6, with_screenshot: bool = False) -> dict:
    """Think → act loop. Returns {final, steps[]} where steps show thought+actions+observations."""
    history: list[dict] = [{"role": "system", "content": providers.SYSTEM_PROMPT + "\n" + TOOL_MANIFEST}]
    history.append({"role": "user", "content": f"GOAL: {goal}\nStart. First reply with tool calls or FINAL."})
    images: list[str] = []
    if with_screenshot:
        try:
            images.append(vc.take_screenshot()["image_b64"])
        except Exception:
            pass
    steps: list[dict] = []
    final = ""
    for step in range(max_steps):
        res = await providers.chat(history, images=images if step == 0 else [], provider=provider, model=model)
        text = res.get("text", "")
        calls = _extract_calls(text)
        if text.strip().upper().startswith("FINAL:") or not calls:
            final = re.sub(r"^FINAL:\s*", "", text.strip(), flags=re.I) or text
            steps.append({"step": step + 1, "thought": text[:1500], "actions": [], "observation": ""})
            break
        obs_parts: list[str] = []
        for call in _order_calls(calls):
            out = await _run_tool(str(call.get("tool", "")), call.get("args", {}) or {}, autopilot=True)
            obs_parts.append(f"{call.get('tool')}: {json.dumps(out)[:1200]}")
        obs = "\n".join(obs_parts)
        steps.append({"step": step + 1, "thought": text[:1500], "actions": _order_calls(calls), "observation": obs[:2000]})
        history.append({"role": "assistant", "content": text[:2000]})
        history.append({"role": "user", "content": f"OBSERVATIONS:\n{obs}\nContinue: more tool calls or FINAL."})
        final = obs
    else:
        final = "Done (max steps). " + (steps[-1]["observation"] if steps else "")
    return {"final": final[:4000], "steps": steps, "provider": provider}

def looks_like_task(msg: str) -> bool:
    m = msg.strip().lower()
    if m.startswith(("/agent", "do:", "run:", "execute:")):
        return True
    verbs = ("open ", "create ", "make ", "delete ", "run ", "execute ", "search ",
             "find ", "install ", "download ", "type ", "click ", "screenshot",
             "list files", "show me", "organize", "rename", "write a file")
    return any(m.startswith(v) for v in verbs)
