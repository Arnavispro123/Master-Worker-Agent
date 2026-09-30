"""Research flow: web search → read pages → answer with sources.

"research X" / "learn about X" goes online, reads real pages, then answers —
works even with weak models, since the pipeline is deterministic.
No API key needed for plumbing; summarization uses the normal AI router
(extractive fallback when fully offline).
"""
from __future__ import annotations
import html as _html
import re
from typing import Optional

from . import tools, providers

VERBS = (
    "research", "learn about", "look up", "lookup", "look-up",
    "study", "find out about", "investigate",
    "deep dive into", "deep dive on", "deep dive",
    "read up on",
)


def extract_query(message: str) -> str | None:
    m = (message or "").strip()
    if len(m) > 300:
        return None
    low = m.lower()
    # strip polite wrappers: "can you research X (for me)(please)"
    low = re.sub(r"^(please\s+|can you\s+|could you\s+|would you\s+|hey jarvis[,\s]*|jarvis[,\s]*)", "", low)
    low = re.sub(r"\s+(for me|please|for me please)\s*$", "", low).strip()
    for v in sorted(VERBS, key=len, reverse=True):
        if low.startswith(v + " ") or low == v:
            q = low[len(v):].strip(" ,.!?;:-").strip()
            # keep original casing from the raw message tail
            if q:
                idx = m.lower().find(q[:20])
                q = m[idx:].strip(" ,.!?;:-").strip() if idx != -1 else q
                # restoration can re-attach a stripped suffix — clean again
                q = re.sub(r"\s+(for me|please)\s*$", "", q, flags=re.I).strip(" ,.!?;:-").strip()
            return q or None
    return None


def is_research_request(message: str) -> bool:
    return extract_query(message) is not None


_TASK_HINTS = ("create", "save", "dump", "write", "download", "folder",
               "file", "open ", "send", "email", "remind", "organize")


def is_compound_task(text: str) -> bool:
    """Research + something else ('...and also create a folder...') needs the agent."""
    t = (text or "").lower()
    return any(h in t for h in _TASK_HINTS)


_SAVE_HINTS = ("create", "save", "dump", "write", "download", "folder", "file")


def wants_save(message: str) -> bool:
    t = (message or "").lower()
    return any(h in t for h in _SAVE_HINTS)


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:40]
    return s or "research"


def _parse_folder(message: str, topic: str) -> str:
    m = (message or "")
    rx = re.search(r"folder(?:\s+on(?:\s+my)?\s+desktop)?\s+(?:named|called|as)\s+([A-Za-z0-9 _-]+)", m, re.I)
    if rx:
        return rx.group(1).strip()
    rx = re.search(r"name\s+it(?:\s+as)?\s+([A-Za-z0-9 _-]+)", m, re.I)
    if rx:
        name = rx.group(1).strip()
        # "name it as nuclear engineering" — trim trailing task words
        name = re.split(r"\s+(and|then|also)\s+", name, flags=re.I)[0].strip()
        if name:
            return name
    return topic.strip() or "research"


async def research_and_save(message: str, provider: str = "auto",
                            model: Optional[str] = None) -> dict | None:
    """'research X and dump it in a desktop folder' — deterministic, no LLM needed.
    Returns None when there's no real task clause (plain research)."""
    low = (message or "").strip()
    # split on save-verbs first ("and dump", ", save") — the verb itself proves intent
    parts = re.split(r"\s+and\s+(save|dump|put|store|create|write)\b|,\s*(save|dump|put|store)\b",
                     low, maxsplit=1, flags=re.I)
    if len(parts) >= 3 or (len(parts) == 2 and parts[1]):
        topic_msg = parts[0]
    else:
        # neutral split ("then", "also") — task clause must show save intent,
        # else it's "learn about file systems" (topic word, not a task)
        parts = re.split(r"\s+and also\s+|\s+then\s+|\s+also\s+", low, maxsplit=1, flags=re.I)
        if len(parts) < 2 or not wants_save(parts[1]):
            return None
        topic_msg = parts[0]
    topic = extract_query(topic_msg)
    if not topic:
        # slash path passes a bare topic ("nuclear engineering and also ...")
        t = re.sub(r"^/research\s+", "", topic_msg.strip(), flags=re.I)
        t = re.sub(r"^(please\s+|can you\s+|could you\s+)", "", t, flags=re.I).strip(" ,.!?;:-")
        topic = t[:200] or None
    if not topic:
        return None
    folder = _parse_folder(low, topic)
    res = await research(topic, provider=provider, model=model)
    full = res.get("text", "")
    # save the works: folder on the real Desktop, file by absolute path
    # (file_write doesn't know the desktop shortcut — pass it the real dir)
    from pathlib import Path as _P
    mk = tools.dir_make(f"desktop/{folder}")
    fname = _slug(topic) or _slug(folder)
    saved = ""
    if mk.get("ok"):
        wr = tools.file_write(str(_P(str(mk["path"])) / f"{fname}.txt"), full)
        if wr.get("ok"):
            saved = str(wr.get("path", ""))
    head = full.split("Sources:")[0].strip()[:700]
    if saved:
        text = (f"Done, sir — researched '{topic}' and saved everything to {saved}.\n\n"
                f"{head}\n\n(Full findings with sources are in the file.)")
    else:
        text = (f"I researched '{topic}' but couldn't save it ({mk.get('error', '?')}).\n\n{head}")
    return {"text": text, "provider": res.get("provider", "local"),
            "model": res.get("model", "research-save"), "sources": res.get("sources", []),
            "saved_to": saved}


def html_to_text(html_doc: str, limit: int = 2500) -> str:
    h = html_doc or ""
    h = re.sub(r"(?is)<(script|style|nav|header|footer|aside|form)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    h = _html.unescape(h)
    h = re.sub(r"\s+", " ", h).strip()
    return h[:limit]


_SKIP_DOMAINS = ("duckduckgo.com", "google.", "bing.com", "yahoo.com")


def _is_placeholder(title: str) -> bool:
    t = (title or "").lower()
    return t.startswith(("no instant result", "search failed"))


def _fallback_urls(query: str, n: int) -> list[str]:
    """Real result URLs when the instant-answer API comes back empty.
    DDG html endpoint (direct result__a links). Wikipedia's API blocks bots,
    so article URLs come via DDG instead."""
    import httpx
    urls: list[str] = []
    try:
        r = httpx.post("https://html.duckduckgo.com/html/",
                       data={"q": query}, timeout=15,
                       headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        r.raise_for_status()
        for m in re.finditer(r'class="result__a" href="([^"]+)"', r.text):
            u = m.group(1).strip()
            if u.startswith("//"):
                u = "https:" + u
            if u.startswith("http") and u not in urls and not any(d in u for d in _SKIP_DOMAINS):
                urls.append(u)
                if len(urls) >= n:
                    break
    except Exception:
        pass
    return urls[:n]


def pick_sentences(text: str, n: int = 2) -> list[str]:
    """First prose-like sentences; skips JS junk and nav crumbs."""
    out: list[str] = []
    for s in re.split(r"(?<=[.!?])\s+", text or ""):
        s = s.strip()
        if len(s) < 40:
            continue
        if "function " in s or "{" in s or "}" in s or "=>" in s:
            continue
        alpha = sum(c.isalpha() or c.isspace() for c in s) / max(1, len(s))
        if alpha < 0.7:
            continue
        out.append(s)
        if len(out) >= n:
            break
    return out


async def research(query: str, provider: str = "auto", model: Optional[str] = None,
                   max_pages: int = 3) -> dict:
    q = (query or "").strip()[:300]
    if not q:
        return {"text": "What should I research, sir?", "provider": "local", "model": "research", "sources": []}
    hits = tools.web_search(q, n=6) or []
    urls: list[str] = []
    for h in hits:
        u = (h.get("url") or "").strip()
        if not u.startswith("http") or u in urls:
            continue
        if any(d in u for d in _SKIP_DOMAINS):
            continue  # redirect wrappers, not articles
        urls.append(u)
        if len(urls) >= max_pages:
            break
    # instant API is often empty — fall back to real result lists
    if not urls:
        urls = _fallback_urls(q, max_pages)
    pages: list[dict] = []
    for u in urls:
        try:
            raw = tools.url_fetch(u)
            txt = html_to_text(raw)
            if len(txt) > 200:
                pages.append({"url": u, "text": txt[:1800]})
        except Exception:
            continue
    if not pages:
        # search snippets only (skip the "nothing found" placeholders)
        snips = [h.get("title", "") for h in hits
                 if h.get("title") and not _is_placeholder(h.get("title", ""))][:5]
        if snips:
            body = "Here's what I found, sir:\n- " + "\n- ".join(snips)
            srcs = [u for u in urls[:3]]
            if srcs:
                body += "\n\nSources:\n" + "\n".join(f"{i+1}. {u}" for i, u in enumerate(srcs))
            return {"text": body, "provider": "local", "model": "research", "sources": srcs}
        return {"text": f"I couldn't find anything on '{q}' online, sir.", "provider": "local", "model": "research", "sources": []}

    ctx = "\n\n".join(f"[{i+1}] {p['url']}\n{p['text']}" for i, p in enumerate(pages))
    res = await providers.chat(
        [{"role": "user",
          "content": f"Research question: {q}\nAnswer using ONLY the sources below, concisely, in plain sentences (no JSON, no code). End with nothing extra.\n\nSOURCES:\n{ctx[:9000]}"}],
        provider=provider, model=model)
    if res.get("provider") == "offline":
        # extractive fallback: first prose sentences of each page
        bits = []
        for p in pages:
            sents = pick_sentences(p["text"], 2) or [p["text"][:220]]
            joined = " ".join(sents).strip()
            if len(joined) >= 60:  # drop nav crumbs
                bits.append(joined)
        if not bits:
            bits = [p["text"][:220] for p in pages[:1]]
        body = f"Here's what I found on '{q}', sir:\n" + "\n".join(f"- {b}" for b in bits)
        srcs = [p["url"] for p in pages]
        body += "\n\nSources:\n" + "\n".join(f"{i+1}. {u}" for i, u in enumerate(srcs))
        return {"text": body, "provider": "local", "model": "research", "sources": srcs}

    srcs = [p["url"] for p in pages]
    body = (res.get("text", "") or "").strip()
    body += "\n\nSources:\n" + "\n".join(f"{i+1}. {u}" for i, u in enumerate(srcs))
    return {"text": body, "provider": res.get("provider", provider), "model": res.get("model", model or "auto"), "sources": srcs}
