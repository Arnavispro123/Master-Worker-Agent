"""JARVIS backend — FastAPI. Serves API + HUD (frontend/) so it works in plain browser too."""
from __future__ import annotations
import base64
import os
import platform
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import AUTOPILOT, CONFIG_SUMMARY, PORT
from . import providers, tools
from . import vision_control as vc
from . import voice as voice_mod
from . import agent as agent_mod
from . import wake as wake_mod
from . import prefs as prefs_mod
from . import fastpath as fastpath_mod
from . import opener as opener_mod
from . import research as research_mod
from . import activity as activity_mod

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

app = FastAPI(title="JARVIS")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── models ──
class ChatIn(BaseModel):
    message: str = ""
    history: list[dict] = []
    provider: str = "auto"
    model: str | None = None
    with_screenshot: bool = False
    agent_mode: bool = False

class VisionAskIn(BaseModel):
    question: str = "What do you see on my screen?"
    provider: str = "auto"
    model: str | None = None

class ControlIn(BaseModel):
    x: int | None = None
    y: int | None = None
    text: str = ""
    key: str = ""
    amount: int = 3
    button: str = "left"
    confirm: bool = False

class ClickTargetIn(BaseModel):
    instruction: str
    provider: str = "auto"
    model: str | None = None
    confirm: bool = False

class AgentIn(BaseModel):
    goal: str
    provider: str = "auto"
    model: str | None = None
    max_steps: int = 6
    with_screenshot: bool = False

class WakeIn(BaseModel):
    words: list[str] | None = None

class KeysIn(BaseModel):
    OPENCODE_API_KEY: str | None = None
    OPENROUTER_API_KEY: str | None = None
    GROQ_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None

# ── basic ──
@app.get("/api/health")
def health():
    return {"ok": True, "time": datetime.now().isoformat(), "system": platform.system(),
            "autopilot": AUTOPILOT or _autopilot_on, "providers": providers.provider_status()}

@app.get("/api/providers/status")
def pstatus():
    return providers.provider_status()

@app.get("/api/providers/models")
async def pmodels(provider: str = "auto", force: bool = False):
    """Live model ids for a provider, right now (cached 1h). Shown in-app."""
    return await providers.list_models(provider, force=force)

@app.get("/api/providers/models-all")
async def pmodels_all(force: bool = False):
    out: dict = {}
    for p in ("opencode", "openrouter", "groq", "gemini", "ollama", "openai", "anthropic"):
        try:
            out[p] = await providers.list_models(p, force=force)
        except Exception as e:
            out[p] = {"models": [], "live": False, "error": str(e)[:200]}
    return out

@app.get("/api/providers/test")
async def ptest(provider: str, model: str | None = None):
    """One-click test: sends 'reply PONG' via a provider+model with the saved key."""
    try:
        r = await providers.chat([{"role": "user", "content": "Reply with exactly: PONG"}], provider=provider, model=model)
        return {"ok": r.get("provider") != "offline", **r}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}

@app.post("/api/keys")
def save_keys(k: KeysIn):
    """Save keys to .env (masked in response)."""
    envp = ROOT / ".env"
    existing = {}
    if envp.exists():
        for line in envp.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                a, b = line.split("=", 1)
                existing[a.strip()] = b.strip()
    for f in ("OPENCODE_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        v = getattr(k, f)
        if v:
            existing[f] = v.strip()
            os.environ[f] = v.strip()
    envp.write_text("\n".join(f"{a}={b}" for a, b in existing.items()) + "\n")
    return {"ok": True, "saved": [f for f in existing if existing[f]]}

# ── chat ──
async def _run_slash(msg: str, provider: str, model: str | None) -> dict | None:
    m = msg.strip()
    if m.startswith("/screenshot"):
        s = vc.take_screenshot()
        return {"text": "Screenshot captured, sir. See the preview panel.", "provider": "system",
                "model": "screenshot", "image": "data:image/jpeg;base64," + s["image_b64"]}
    if m.startswith("/see") or m.startswith("/vision"):
        q = m.split(" ", 1)[1] if " " in m else "What do you see?"
        return await vision_ask(VisionAskIn(question=q, provider=provider, model=model))
    if m.startswith("/click"):
        instr = m.split(" ", 1)[1] if " " in m else "the close button"
        return await agent_click(ClickTargetIn(instruction=instr, provider=provider, confirm=True))
    if m.startswith("/type"):
        t = m.split(" ", 1)[1] if " " in m else ""
        return {"control": vc.type_text(t, confirm=True, autopilot=True), "text": f"Typed {len(t)} chars."}
    if m.startswith("/open"):
        t = m.split(" ", 1)[1] if " " in m else ""
        return {"control": tools.open_target(t), "text": f"Opening {t}."}
    if m.startswith("/remember"):
        rest = m.split(" ", 1)[1] if " " in m else ""
        tools.remember("note-" + datetime.now().isoformat()[:16], rest)
        return {"text": "Committed to memory, sir.", "provider": "system", "model": "memory"}
    if m.startswith("/remind"):
        parts = m.split(" ", 2)
        mins = 10
        try: mins = int(parts[1].lstrip("in"))
        except Exception: pass
        msg2 = parts[2] if len(parts) > 2 else "reminder"
        r = tools.remind(msg2, mins)
        return {"text": f"Reminder set for {r['due']}.", "provider": "system", "model": "reminder"}
    if m.startswith("/search"):
        q = m.split(" ", 1)[1] if " " in m else ""
        return {"text": "\n".join(f"- {x['title']} ({x['url']})" for x in tools.web_search(q)), "provider": "system", "model": "search"}
    if m.startswith("/research"):
        q = m.split(" ", 1)[1] if " " in m else ""
        if not q:
            return {"text": "What should I research, sir?", "provider": "system", "model": "research"}
        if research_mod.wants_save(q):
            rs = await research_mod.research_and_save(q, provider=provider, model=model)
            if rs:
                return rs
        return await research_mod.research(q, provider=provider, model=model)
    return None

@app.post("/api/chat")
async def chat_api(body: ChatIn):
    ms = body.message.strip()
    # deterministic research-and-save FIRST (no LLM, works offline) —
    # beats agent routing so a dead provider can't block it
    if not body.with_screenshot and research_mod.wants_save(ms):
        rs = await research_mod.research_and_save(ms, provider=body.provider, model=body.model)
        if rs:
            return rs
    # agent mode + multi-step /research ("...and also create a folder...") → full agent
    if body.agent_mode and ms.lower().startswith("/research"):
        _q = ms.split(" ", 1)[1] if " " in ms else ""
        if _q and research_mod.is_compound_task(_q):
            res = await agent_mod.run_goal(
                f"Research this and do everything asked: {_q}. "
                "Use the research tool for the web part, dir_make/file_write for saving. "
                "You have full autonomy — act, don't ask.",
                provider=body.provider, model=body.model, with_screenshot=body.with_screenshot)
            return {"text": res["final"], "provider": f"agent:{body.provider}", "model": body.model or "auto",
                    "steps": res["steps"]}
    if body.message.strip().startswith("/"):
        slash = await _run_slash(body.message, body.provider, body.model)
        if slash:
            return slash
    # clock/date: instant local answer — always first (even in agent mode,
    # pure questions are not tasks)
    if not body.with_screenshot:
        fp = fastpath_mod.try_fastpath(body.message)
        if fp:
            return fp
        op = opener_mod.try_open(body.message)
        if op:
            return op
        # research/learn: go online, read pages, answer with sources
        rq = research_mod.extract_query(body.message)
        if rq:
            if research_mod.wants_save(body.message):
                rs = await research_mod.research_and_save(body.message, provider=body.provider, model=body.model)
                if rs:
                    return rs
            return await research_mod.research(rq, provider=body.provider, model=body.model)
    # agentic: "do this for me" → think + execute tools on its own
    if (body.agent_mode or agent_mod.looks_like_task(body.message)) and not body.message.strip().startswith("/"):
        if body.agent_mode or body.message.strip().lower().startswith(("/agent", "do:", "run:", "execute:")) or agent_mod.looks_like_task(body.message):
            goal = body.message
            for pfx in ("/agent", "do:", "run:", "execute:"):
                if goal.strip().lower().startswith(pfx):
                    goal = goal.split(" ", 1)[1] if " " in goal else goal
                    break
            # only auto-run for explicit prefixes or agent_mode toggle (safe)
            if body.agent_mode or body.message.strip().lower().startswith(("/agent", "do:", "run:", "execute:")):
                res = await agent_mod.run_goal(goal, provider=body.provider, model=body.model,
                                               with_screenshot=body.with_screenshot)
                return {"text": res["final"], "provider": f"agent:{body.provider}", "model": body.model or "auto",
                        "steps": res["steps"]}
    images: list[str] = []
    if body.with_screenshot:
        try:
            images.append(vc.take_screenshot()["image_b64"])
        except Exception as e:
            return {"text": f"Screenshot failed: {e}", "provider": "system", "model": "error"}
    res = await providers.chat([*body.history, {"role": "user", "content": body.message}],
                               images=images, provider=body.provider, model=body.model)
    return res

# ── vision ──
@app.get("/api/vision/screenshot")
def screenshot():
    try:
        return vc.take_screenshot()
    except Exception as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=500)

@app.post("/api/vision/ask")
async def vision_ask(body: VisionAskIn):
    try:
        s = vc.take_screenshot()
    except Exception as e:
        return {"text": f"Screenshot failed: {e}", "provider": "system", "model": "error"}
    res = await providers.chat([{"role": "user", "content": body.question}],
                               images=[s["image_b64"]], provider=body.provider, model=body.model)
    res["image"] = "data:image/jpeg;base64," + s["image_b64"]
    return res

# ── control ──
_autopilot_on = AUTOPILOT

@app.post("/api/control/mode")
def set_mode(body: dict):
    global _autopilot_on
    _autopilot_on = bool(body.get("autopilot", False))
    return {"autopilot": _autopilot_on}

@app.post("/api/control/click")
def c_click(b: ControlIn):
    return vc.click(b.x, b.y, b.button, b.confirm, _autopilot_on)

@app.post("/api/control/type")
def c_type(b: ControlIn):
    return vc.type_text(b.text, b.confirm, _autopilot_on)

@app.post("/api/control/press")
def c_press(b: ControlIn):
    return vc.press(b.key or "enter")

@app.post("/api/control/scroll")
def c_scroll(b: ControlIn):
    return vc.scroll(b.amount)

@app.post("/api/agent/click-target")
async def agent_click(b: ClickTargetIn):
    """Screenshot → LLM returns 0-1000 coords → click (gated)."""
    try:
        s = vc.take_screenshot()
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    res = await providers.chat(
        [{"role": "user", "content": f"Locate: '{b.instruction}'. Reply ONLY with JSON {{\"x\": <0-1000>, \"y\": <0-1000>}}."}],
        images=[s["image_b64"]], provider=b.provider, model=b.model)
    xy = vc.parse_xy_from_llm(res.get("text", ""))
    if not xy:
        return {"ok": False, "brain": res, "error": "model did not return coordinates", "say": res.get("text", "")}
    if not (b.confirm or _autopilot_on):
        return {"ok": False, "need_confirm": True, "x": xy[0], "y": xy[1], "say": res.get("text", "")}
    clicked = vc.click_normalized(*xy)
    return {"ok": True, "clicked": clicked, "say": f"Clicked {b.instruction} at {xy}."}

# ── voice ──
@app.post("/api/tts")
def tts(body: dict):
    out = voice_mod.speak(str(body.get("text", ""))[:600])
    if out.endswith(".mp3") and os.path.exists(out):
        return FileResponse(out, media_type="audio/mpeg")
    return {"ok": True, "note": out or "use browser TTS"}

@app.post("/api/stt")
async def stt(f: UploadFile):
    import tempfile
    suf = ".webm" if (f.filename or "").endswith("webm") else ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suf) as t:
        t.write(await f.read())
        path = t.name
    return {"text": voice_mod.transcribe_file(path)}

# ── tools ──
@app.post("/api/tools/shell")
def t_shell(b: dict):
    return tools.shell_run(str(b.get("cmd", ""))[:2000])

@app.post("/api/tools/search")
def t_search(b: dict):
    return tools.web_search(str(b.get("q", ""))[:300])

@app.post("/api/tools/open")
def t_open(b: dict):
    return tools.open_target(str(b.get("target", "")))

# ── agent: think on its own + execute ──
@app.post("/api/agent/run")
async def agent_run(b: AgentIn):
    res = await agent_mod.run_goal(b.goal, provider=b.provider, model=b.model,
                                   max_steps=max(1, min(10, b.max_steps)),
                                   with_screenshot=b.with_screenshot)
    return res

# ── wake word (offline, no keys) ──
@app.get("/api/wake/status")
def w_status():
    return wake_mod.status()

@app.post("/api/wake/start")
def w_start(b: WakeIn | None = None):
    return wake_mod.start((b.words if b else None))

@app.post("/api/wake/stop")
def w_stop():
    return wake_mod.stop()

@app.get("/api/wake/poll")
def w_poll():
    return wake_mod.poll()

# ── activity bus (orb + HUDs stay in sync no matter who acted) ──
class ActivityIn(BaseModel):
    kind: str = "idle"
    text: str = ""

@app.post("/api/activity")
def a_push(b: ActivityIn):
    return activity_mod.push(b.kind, b.text) or {"ok": True}

@app.get("/api/activity/poll")
def a_poll(since: int = 0):
    return {"events": activity_mod.poll(since)}

# ── user preferences (provider/model/switches/TTS — no keys, survives restart) ──
@app.get("/api/prefs")
def p_prefs():
    return prefs_mod.load()

@app.post("/api/prefs")
def p_prefs_save(body: dict):
    return prefs_mod.save(body or {})

# ── serve HUD ──
if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="hud")

if __name__ == "__main__":
    import uvicorn
    print(f"JARVIS backend on http://127.0.0.1:{PORT}  keys={CONFIG_SUMMARY}")
    uvicorn.run("backend.app:app", host="127.0.0.1", port=PORT, reload=False)
