# JARVIS — Master Build Prompt
> The exact prompt used to generate this repo from scratch. Paste this into any AI coder (OpenCode, Claude, GPT, etc.) to rebuild Jarvis.

---

## ROLE
You are a senior full-stack + AI systems engineer. Build **JARVIS** — a free-or-paid, local-first personal AI assistant inspired by Iron Man, with voice, vision, screen control, and a beautiful HUD.

## STACK (mandatory)
- **Backend:** Python 3.10+ with FastAPI (`backend/`)
- **Frontend/Shell:** Electron + HTML/CSS/JS, no framework required (`electron/`, `frontend/`)
- Backend and Electron talk over HTTP `http://127.0.0.1:8765` + WebSocket for streaming.
- Must run on Windows, macOS, Linux with one command.

## CORE REQUIREMENTS

### 1. AI Router — "do anything, free or paid via API keys"
Implement `backend/providers.py` with a unified interface:
```python
chat(messages, images=[], model=None, provider="auto") -> str | stream
list_models() -> [...]
```
Support providers, in priority order for AUTO mode:
1. `opencode` (OpenCode Zen) — auto-load key from `~/.local/share/opencode/auth.json` (`{opencode.apiKey}`) or `OPENCODE_API_KEY` env. OpenAI-compatible base `https://opencode.ai/zen/v1` (configurable via `OPENCODE_BASE_URL`), with `/chat/completions` tried first across free models (`big-pickle`, `kimi-k2.5`, `glm-5`…) then the `/responses` API (`muse-spark-*-free`).
2. `openrouter` — `https://openrouter.ai/api/v1`, key `OPENROUTER_API_KEY`. Default free model `meta-llama/llama-3.3-70b-instruct:free`, vision `qwen/qwen2-vl-72b-instruct:free` (fallback list in code).
3. `groq` — `https://api.groq.com/openai/v1`, key `GROQ_API_KEY`. Default `llama-3.3-70b-versatile`.
4. `gemini` — Google Generative AI, key `GEMINI_API_KEY` / `GOOGLE_API_KEY`. Default `gemini-1.5-flash`.
5. `ollama` — local free, `http://localhost:11434`, no key. Default `llama3.1`.
6. `openai` — paid, key `OPENAI_API_KEY`. Default `gpt-4o-mini`.
7. `anthropic` — paid, key `ANTHROPIC_API_KEY`. Default `claude-3-5-sonnet-latest`.
- If `provider="auto"`, try in order: configured paid keys first if present, else free chain (opencode → openrouter-free → groq → gemini → ollama). Never crash if a key is missing — skip and log.
- All OpenAI-compatible providers share one `_openai_compat_chat()` helper using only `httpx` (no heavy SDKs required).
- Support `images: [base64_or_data_url]` → convert to OpenAI vision content blocks; for Anthropic/Gemini use their native format or fallback to OpenAI-compat if model supports it.
- `.env.example` must list ALL keys. Frontend Settings panel must let users paste keys (stored in backend `.env` + never logged).

### 2. Voice — recognition + speech-to-text + TTS + wake word
- **Frontend:** Web Speech STT in browsers (Electron's Chromium lacks the key → mic→WAV→`POST /api/stt` instead, with in-code VAD + 16kHz WAV encoder). TTS prefers backend edge-TTS mp3 (`en-GB-RyanNeural` +25%), falls back to a forced-male browser voice with sentence-chunked speech. Push-to-talk + `Alt+J`.
- **Backend (`voice.py`, `wake.py`):** sounddevice capture @16kHz + Google STT (keyless), adaptive noise-floor threshold (recalibrated every listen — never a fixed magic number), unlimited hear time with silence-stop, stop phrases, hesitation tolerance, wake-word settle window, fuzzy wake matching, thread-generation guards, STT error accounting, `GET /api/wake/status` diagnostics + `POST /api/wake/test` mic self-test.
- Expose `POST /api/stt`, `POST /api/tts`, `GET /api/wake/status`, `POST /api/wake/start|stop`, `GET /api/wake/poll`, `POST /api/wake/test`.

### 3. Vision — "look at the user's screen"
- `backend/vision_control.py`:
  - `take_screenshot(monitor=0, max_width=1280) -> {image_b64, w, h}` using `mss` + `PIL`.
  - `POST /api/vision/screenshot` returns JPEG base64.
  - `POST /api/vision/ask {question, provider, model}` → screenshot + question → providers.chat with image.
- Frontend shows live screen thumbnail + "What do you see?" button.

### 4. Control — "click and stuff if the model supports it"
- `pyautogui` wrappers with **safety gate**:
  - `move/click/double_click/right_click/drag/scroll/type/press/hotkey`
  - `AI_CLICK` requires `confirm=true` unless `JARVIS_DANGER_AUTOPILOT=1`.
  - `POST /api/control/{action}` + `POST /api/agent/click-target {instruction}` where LLM gets screenshot + returns `{x%, y%}` coordinates, then backend clicks.
- Frontend "Allow autopilot" toggle, default OFF. Every AI click shows toast + highlight ring.

### 5. Tools — "do anything"
`backend/tools.py`: file read/write/list, `dir_make` (Desktop/Documents/Downloads + OneDrive aware, remaps hallucinated `C:\Users\…\Desktop` paths onto the real Desktop), guarded `file_delete`, shell run (blocklist + timeout), web search (DuckDuckGo free, no key), URL fetch, memory (SQLite), reminders, open app/URL.
`backend/research.py`: deterministic research flow (search → read pages → answer with clickable sources, extractive fallback offline) + `research_and_save` for research-to-folder tasks. `backend/opener.py`: deterministic open/play/launch (known sites + Windows apps). `backend/fastpath.py`: instant clock/date answers.
`backend/agent.py`: think→act loop with strict + prose-tolerant tool parsing (`name('args')`, numbered lists), reads-before-writes ordering, full autonomy (never asks for confirmation in text).
Expose via `POST /api/tools/*`, `POST /api/agent/run`.

### 6. UI — "good looking interface"
Modern glassy dark HUD: welcome hero with suggestion chips, typing indicator, timestamps, collapsible agent-trace `<details>`, linkified sources, per-bubble Replay/Copy/Stop, confirm-click button, API-key vault modal with live per-provider models + test buttons, command palette modal (`Ctrl+K`, no native prompts), vision modal, screen preview, wake ears selector (window/backend), mic self-test button, prefs persisted server-side (`preferences.json`), model disk cache (`models_cache.json`).
Files: `frontend/index.html`, `frontend/styles.css`, `frontend/renderer.js`, `frontend/orb.html`, `frontend/place.html`, `electron/main.js` (tray, single-instance, backend reuse), `electron/preload.js` (HUD→orb IPC), `electron/tray.png`.
Must work BOTH as Electron AND as plain browser via `python main.py` → `http://127.0.0.1:8765`.

### 8. Orb + presence
- Transparent always-on-top circular orb (`orb.html`), bottom-right by default: 8-zone first-run picker (`place.html`), free dragging with persisted position, system tray with hide-to-tray (background running).
- Orb shows live state + last action, voice-reactive radius + circular beats visualizer (HUD streams analyser amplitude), radiating rings.
- Busy-state visibility (stays while speaking/listening/working), backend activity bus (`POST/GET /api/activity`) so the orb reacts no matter which window acted; wake command queue is drain-once (no double-send), orb peeks display-only, 60s TTL + caps.

### 7. Extra imagination (go wild)
- System prompt with personality ("You are Jarvis... witty, loyal, concise").
- Command palette commands: `/screenshot`, `/see`, `/click`, `/type`, `/open`, `/remember`, `/remind`, `/clear`.
- Offline fallback: if no keys at all → Ollama → rule-based canned replies (never blank screen).
- Startup greeting with time, date, system stats.
- Logging + `/api/health`, `/api/providers/status`.

## FILE TREE TO GENERATE
```
main.py  PROMPT.md  README.md  LICENSE  .gitignore  .env.example
requirements.txt  package.json
backend/__init__.py  backend/config.py  backend/app.py
backend/providers.py  backend/agent.py  backend/research.py  backend/opener.py
backend/fastpath.py  backend/voice.py  backend/wake.py  backend/vision_control.py
backend/tools.py  backend/prefs.py  backend/activity.py
backend/test_opencode_key.py
electron/main.js  electron/preload.js  electron/tray.png
frontend/index.html  frontend/styles.css  frontend/renderer.js
frontend/orb.html  frontend/place.html
scripts/publish-github.ps1  scripts/start-backend.ps1  start-jarvis.bat
```

## ACCEPTANCE TESTS
1. `pip install -r requirements.txt` succeeds.
2. `python main.py` → backend healthy at `GET /api/health`, HUD opens, no tracebacks.
3. `python backend/test_opencode_key.py` → uses OpenCode key from auth.json if present, prints masked result, never prints full key.
4. `npm install && npm start` opens HUD + tray + orb; single instance only; closing hides to tray.
5. First run shows the 8-zone orb picker; drag persists position across restarts.
6. Voice: mic test reports healthy; "jarvis what time is it" → instant local clock answer, spoken; backend stays silent in Electron (no double voice).
7. Screenshot + "what do you see" returns description when a vision model/key is configured.
8. Click test with confirm gate works; agent `/research X and save to desktop` creates folder + file with sources.
9. `.env`, `preferences.json`, `models_cache.json`, `*.db` never appear in `git ls-files`.

## CONSTRAINTS
- No hardcoded API keys. Mask keys in logs (`sk-...abcd`). API never accepts arbitrary prefs keys.
- Deps: `fastapi uvicorn httpx python-dotenv pillow mss pyautogui apscheduler python-multipart edge-tts SpeechRecognition sounddevice soundfile numpy`. Everything else optional with try/except.
- Every change ships with: `py_compile`, `node --check`, a behavior test of touched flows, and a regression pass over wake→chat→voice when voice code moves.
- MIT license.

Build all files now, complete and runnable. No placeholders.
