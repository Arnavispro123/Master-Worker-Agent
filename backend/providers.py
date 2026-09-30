"""Unified AI router: free or paid via API keys. Auto-fallback chain."""
from __future__ import annotations
import os
import re
from typing import AsyncIterator, Optional
import httpx

from .config import SYSTEM_PROMPT, get_key, mask

TIMEOUT = 90.0

FREE_OPENROUTER_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "google/gemma-3-27b-it:free",
]
VISION_FALLBACK = "qwen/qwen2-vl-72b-instruct:free"


def _openai_messages(messages: list[dict], images: list[str]) -> list[dict]:
    """Convert to OpenAI content blocks; images = b64 or data-urls."""
    if not images:
        return messages
    img_blocks = []
    for im in images:
        url = im if im.startswith("data:") else f"data:image/jpeg;base64,{im}"
        img_blocks.append({"type": "image_url", "image_url": {"url": url}})
    out = [m for m in messages]
    # attach images to last user message
    for i in range(len(out) - 1, -1, -1):
        if out[i].get("role") == "user":
            text = out[i].get("content", "")
            out[i] = {"role": "user", "content": [{"type": "text", "text": str(text)}, *img_blocks]}
            break
    else:
        out.append({"role": "user", "content": [{"type": "text", "text": "Describe this image."}, *img_blocks]})
    return out


async def _openai_compat_chat(base_url: str, api_key: str, model: str,
                               messages: list[dict], images: list[str],
                               stream: bool = False) -> str | AsyncIterator[str]:
    payload = {
        "model": model,
        "messages": _openai_messages(messages, images),
        "stream": stream,
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    # OpenRouter niceties (optional, harmless elsewhere)
    if "openrouter" in base_url:
        headers["HTTP-Referer"] = "https://github.com/jarvis"
        headers["X-Title"] = "JARVIS"
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        if not stream:
            r = await c.post(f"{base_url.rstrip('/')}/chat/completions", json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]
        # streaming not used by backend yet; placeholder
        r = await c.post(f"{base_url.rstrip('/')}/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        async def gen():
            yield data["choices"][0]["message"]["content"]
        return gen()


async def _ollama_chat(model: str, messages: list[dict], images: list[str]) -> str:
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    prompt_msgs = "\n".join(f"{m['role']}: {m['content']}" for m in messages[-8:])
    payload: dict = {"model": model, "prompt": prompt_msgs, "stream": False}
    if images:
        payload["images"] = [im.split(",", 1)[-1] for im in images]
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{base.rstrip('/')}/api/generate", json=payload)
        r.raise_for_status()
        return r.json().get("response", "")


async def _gemini_chat(api_key: str, model: str, messages: list[dict], images: list[str]) -> str:
    import base64
    model = model or "gemini-1.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    contents = []
    for m in messages:
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": str(m.get("content", ""))}]})
    if images and contents:
        for im in images:
            b64 = im.split(",", 1)[-1]
            try:
                base64.b64decode(b64)  # validate
                contents[-1]["parts"].append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})
            except Exception:
                continue
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(url, json={"contents": contents})
        r.raise_for_status()
        data = r.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            return str(data)[:2000]


async def _opencode_chat(api_key: str, model: str, messages: list[dict], images: list[str]) -> tuple[str, str]:
    """OpenCode Zen: correct base https://opencode.ai/zen/v1.
    Tries chat/completions (open models) then Responses API (GPT/Grok/Muse).
    Returns (text, used_model)."""
    base = os.getenv("OPENCODE_BASE_URL", "https://opencode.ai/zen/v1").rstrip("/")
    chat_models = [model] if model else []
    # free chat-completions models first, then paid-ish defaults
    chat_models += ["big-pickle", "kimi-k2.5", "glm-5", "deepseek-v4-flash", "qwen3.8-max"]
    seen = set()
    last_err = ""
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        for m in chat_models:
            if m in seen:
                continue
            seen.add(m)
            try:
                r = await c.post(f"{base}/chat/completions",
                                 headers={"Authorization": f"Bearer {api_key}"},
                                 json={"model": m, "messages": _openai_messages(messages, images)})
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"], m
            except Exception as e:
                last_err = str(e)[:200]
                continue
        # Responses API (muse-spark, gpt, grok) — text only
        resp_models = ([model] if model else []) + ["muse-spark-1.3-contributor-free", "muse-spark-1.3"]
        text_in = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in messages[-10:])
        for m in resp_models:
            if m in seen:
                continue
            try:
                r = await c.post(f"{base}/responses",
                                 headers={"Authorization": f"Bearer {api_key}"},
                                 json={"model": m, "input": text_in})
                r.raise_for_status()
                data = r.json()
                # extract text from Responses API shapes
                txt = ""
                if isinstance(data, dict):
                    if data.get("output_text"):
                        txt = data["output_text"]
                    else:
                        for item in data.get("output", []) or []:
                            for part in item.get("content", []) or []:
                                if part.get("text"):
                                    txt += part["text"]
                                elif part.get("type") == "output_text":
                                    txt += part.get("text", "")
                if txt.strip():
                    return txt, m
            except Exception as e:
                last_err = str(e)[:200]
                continue
    raise RuntimeError(f"opencode zen failed: {last_err}")


async def _anthropic_chat(api_key: str, model: str, messages: list[dict], images: list[str]) -> str:
    import base64
    model = model or "claude-3-5-sonnet-latest"
    sys = SYSTEM_PROMPT
    msgs = []
    for m in messages:
        if m["role"] == "system":
            sys = str(m["content"])
            continue
        content: list[dict] = [{"type": "text", "text": str(m.get("content", ""))}]
        if m["role"] == "user" and images and m is messages[-1]:
            for im in images:
                b64 = im.split(",", 1)[-1]
                try:
                    base64.b64decode(b64)
                    content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
                except Exception:
                    continue
        msgs.append({"role": m["role"], "content": content})
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post("https://api.anthropic.com/v1/messages",
                         headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                         json={"model": model, "max_tokens": 2000, "system": sys, "messages": msgs})
        r.raise_for_status()
        data = r.json()
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def provider_status() -> dict:
    return {
        "opencode": {"configured": bool(get_key("OPENCODE_API_KEY")), "key": mask(get_key("OPENCODE_API_KEY")), "free": True},
        "openrouter": {"configured": bool(get_key("OPENROUTER_API_KEY")), "key": mask(get_key("OPENROUTER_API_KEY")), "free": True},
        "groq": {"configured": bool(get_key("GROQ_API_KEY")), "key": mask(get_key("GROQ_API_KEY")), "free": True},
        "gemini": {"configured": bool(get_key("GEMINI_API_KEY")), "key": mask(get_key("GEMINI_API_KEY")), "free": True},
        "ollama": {"configured": True, "key": "local", "free": True},
        "openai": {"configured": bool(get_key("OPENAI_API_KEY")), "key": mask(get_key("OPENAI_API_KEY")), "free": False},
        "anthropic": {"configured": bool(get_key("ANTHROPIC_API_KEY")), "key": mask(get_key("ANTHROPIC_API_KEY")), "free": False},
    }


# ── live model catalog (shown in-app, refreshed at the time of request) ──
# memory cache + disk cache (models_cache.json) so reopening the app is instant.
_MODELS_CACHE: dict[str, dict] = {}
_MODELS_TTL = 3600.0

def _disk_cache_path():
    from pathlib import Path
    return Path(__file__).resolve().parent.parent / "models_cache.json"

def _disk_get(p: str):
    import json, time
    try:
        fp = _disk_cache_path()
        if not fp.exists():
            return None
        data = json.loads(fp.read_text())
        e = data.get(p) if isinstance(data, dict) else None
        if e and time.time() - float(e.get("ts", 0)) < _MODELS_TTL and e.get("models"):
            _MODELS_CACHE[p] = {"ts": e["ts"], "models": e["models"]}
            return e["models"]
    except Exception:
        pass
    return None

def _disk_set(p: str, models: list[str]):
    import json, time
    try:
        fp = _disk_cache_path()
        data = {}
        if fp.exists():
            try:
                data = json.loads(fp.read_text()) or {}
            except Exception:
                data = {}
        data[p] = {"ts": time.time(), "models": models}
        fp.write_text(json.dumps(data))
    except Exception:
        pass

CURATED = {
    "anthropic": ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest", "claude-opus-4-5"],
    "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
    "gemini": ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"],
    "openai": ["gpt-4o-mini", "gpt-4o", "o4-mini"],
    "ollama": ["llama3.1", "qwen2.5", "mistral"],
    "openrouter": FREE_OPENROUTER_MODELS,
    "opencode": ["big-pickle", "kimi-k2.5", "glm-5", "deepseek-v4-flash", "muse-spark-1.3-contributor-free"],
}

def _cache_get(p: str):
    import time
    e = _MODELS_CACHE.get(p)
    if e and time.time() - e["ts"] < _MODELS_TTL:
        return e["models"]
    return None

def _cache_set(p: str, models: list[str]):
    import time
    _MODELS_CACHE[p] = {"ts": time.time(), "models": models}

async def list_models(provider: str, force: bool = False) -> dict:
    """Live model ids for a provider, right now. Falls back to curated list."""
    provider = (provider or "auto").lower()
    if provider == "auto":
        return {"models": [], "live": False, "note": "pick a provider to list models"}
    if not force:
        hit = _cache_get(provider)
        if hit:
            return {"models": hit, "live": True, "cached": True}
        disk = _disk_get(provider)
        if disk:
            return {"models": disk, "live": True, "cached": True, "disk": True}
    models: list[str] = []
    live = False
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            if provider == "openrouter":
                r = await c.get("https://openrouter.ai/api/v1/models")
                r.raise_for_status()
                models = [m.get("id", "") for m in r.json().get("data", []) if m.get("id")][:120]
                live = True
            elif provider == "groq" and get_key("GROQ_API_KEY"):
                r = await c.get("https://api.groq.com/openai/v1/models",
                                headers={"Authorization": f"Bearer {get_key('GROQ_API_KEY')}"})
                r.raise_for_status()
                models = [m.get("id", "") for m in r.json().get("data", [])][:120]
                live = True
            elif provider == "openai" and get_key("OPENAI_API_KEY"):
                r = await c.get("https://api.openai.com/v1/models",
                                headers={"Authorization": f"Bearer {get_key('OPENAI_API_KEY')}"})
                r.raise_for_status()
                models = sorted(m.get("id", "") for m in r.json().get("data", []))[:120]
                live = True
            elif provider == "gemini" and get_key("GEMINI_API_KEY"):
                r = await c.get("https://generativelanguage.googleapis.com/v1beta/models",
                                params={"key": get_key("GEMINI_API_KEY")})
                r.raise_for_status()
                models = [m.get("name", "").split("/")[-1] for m in r.json().get("models", [])][:120]
                live = True
            elif provider == "ollama":
                base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
                r = await c.get(f"{base}/api/tags")
                r.raise_for_status()
                models = [m.get("name", "") for m in r.json().get("models", [])] or list(CURATED["ollama"])
                live = True
            elif provider == "opencode" and get_key("OPENCODE_API_KEY"):
                base = os.getenv("OPENCODE_BASE_URL", "https://opencode.ai/zen/v1").rstrip("/")
                # try with key, fall back to public list
                for headers in ({"Authorization": f"Bearer {get_key('OPENCODE_API_KEY')}"}, {}):
                    try:
                        r = await c.get(f"{base}/models", headers=headers)
                        r.raise_for_status()
                        data = r.json()
                        items = data.get("data", data.get("models", [])) if isinstance(data, dict) else data
                        models = [(m.get("id") or m.get("name", "")) for m in items if isinstance(m, dict)][:150]
                        models = [m for m in models if m]
                        if models:
                            live = True
                            break
                    except Exception:
                        continue
    except Exception:
        pass
    if not models:
        models = list(CURATED.get(provider, []))
    else:
        _cache_set(provider, models)
        _disk_set(provider, models)
    return {"models": models, "live": live, "cached": False}


async def chat(messages: list[dict], images: Optional[list[str]] = None,
               provider: str = "auto", model: Optional[str] = None) -> dict:
    """Try providers in order. Returns {text, provider, model}. Never raises blank."""
    images = images or []
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + [m for m in messages if m.get("content")]
    errors: dict[str, str] = {}

    chain: list[str] = []
    if provider != "auto":
        chain = [provider]
    else:
        # paid first if present, else free chain
        st = provider_status()
        if st["openai"]["configured"]:
            chain.append("openai")
        if st["anthropic"]["configured"]:
            chain.append("anthropic")
        chain += ["opencode", "openrouter", "groq", "gemini", "ollama"]

    for p in chain:
        try:
            if p == "opencode" and get_key("OPENCODE_API_KEY"):
                t, used = await _opencode_chat(get_key("OPENCODE_API_KEY"), model or "", msgs, images)
                return {"text": str(t), "provider": "opencode", "model": used}
            if p == "openrouter" and get_key("OPENROUTER_API_KEY"):
                m = model or (VISION_FALLBACK if images else FREE_OPENROUTER_MODELS[0])
                t = await _openai_compat_chat("https://openrouter.ai/api/v1", get_key("OPENROUTER_API_KEY"), m, msgs, images)
                return {"text": str(t), "provider": "openrouter", "model": m}
            if p == "groq" and get_key("GROQ_API_KEY") and not images:
                m = model or "llama-3.3-70b-versatile"
                t = await _openai_compat_chat("https://api.groq.com/openai/v1", get_key("GROQ_API_KEY"), m, msgs, images)
                return {"text": str(t), "provider": "groq", "model": m}
            if p == "gemini" and get_key("GEMINI_API_KEY"):
                m = model or "gemini-1.5-flash"
                t = await _gemini_chat(get_key("GEMINI_API_KEY"), m, msgs, images)
                return {"text": str(t), "provider": "gemini", "model": m}
            if p == "ollama":
                m = model or "llama3.1"
                try:
                    t = await _ollama_chat(m, msgs, images)
                    if t.strip():
                        return {"text": str(t), "provider": "ollama", "model": m}
                except Exception as e:
                    errors[p] = str(e)[:200]
                    continue
            if p == "openai" and get_key("OPENAI_API_KEY"):
                m = model or "gpt-4o-mini"
                t = await _openai_compat_chat("https://api.openai.com/v1", get_key("OPENAI_API_KEY"), m, msgs, images)
                return {"text": str(t), "provider": "openai", "model": m}
            if p == "anthropic" and get_key("ANTHROPIC_API_KEY"):
                m = model or "claude-3-5-sonnet-latest"
                t = await _anthropic_chat(get_key("ANTHROPIC_API_KEY"), m, msgs, images)
                return {"text": str(t), "provider": "anthropic", "model": m}
            errors[p] = "missing key or unsupported"
        except Exception as e:
            errors[p] = str(e)[:300]
            continue

    # offline fallback — never blank, and human-readable (raw trace stays in `errors`)
    # quote the real user question, never internal OBSERVATIONS scaffolding
    last = ""
    for m in reversed(msgs):
        c = str(m.get("content", ""))
        if m.get("role") == "user" and c.strip() and not c.lstrip().upper().startswith("OBSERVATIONS"):
            last = re.sub(r"^GOAL:\s*", "", c.strip(), flags=re.I)
            break
    short = "; ".join(f"{k}: {_short_err(v)}" for k, v in list(errors.items())[:3])
    fallback = (f"Yes, sir — I couldn't reach any AI right now ({short}). "
                f"Add a free key (OpenCode / OpenRouter / Groq / Gemini) or start Ollama, "
                f"and I'll be at full power. You asked: '{str(last)[:200]}'")
    return {"text": fallback, "provider": "offline", "model": "fallback", "errors": errors}


def _short_err(e: str) -> str:
    """One-line, URL-free reason for humans (and TTS)."""
    e = (e or "").split("\n")[0]
    e = re.sub(r"https?://\S+", "", e)
    e = re.sub(r"\s+", " ", e).strip()
    if "429" in e or "rate" in e.lower():
        return "rate-limited — switch provider or wait a minute"
    if "402" in e:
        return "needs billing/credits on that account"
    if "401" in e or "403" in e or "invalid" in e.lower() and "key" in e.lower():
        return "bad or expired key"
    if "404" in e:
        return "bad endpoint/model name"
    if "missing key" in e.lower():
        return "no key saved"
    if "connect" in e.lower() or "refused" in e.lower():
        return "not running locally?"
    return e[:110]
