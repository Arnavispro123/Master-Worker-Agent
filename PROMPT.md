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
1. `opencode` (OpenCode Zen) — auto-load key from `~/.local/share/opencode/auth.json` (`{opencode.apiKey}`) or `OPENCODE_API_KEY` env. OpenAI-compatible base `https://opencode.ai/api/zen/v1` (configurable via `OPENCODE_BASE_URL`). This lets users test for free with their OpenCode key.
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
- **Frontend (free, zero-install):** Web Speech API `webkitSpeechRecognition` for STT + `speechSynthesis` for TTS. Push-to-talk button + `J` hotkey.
- **Backend (optional high-quality):** `backend/voice.py` with:
  - `transcribe_file(path)` using `faster-whisper` if installed, else `SpeechRecognition`.
  - `speak(text)` using `edge-tts` if installed, else `pyttsx3`, else no-op.
  - Wake-word listener thread for "jarvis" / "hey jarvis" (vosk or SpeechRecognition keyword; must not crash if deps missing).
- Expose `POST /api/stt`, `POST /api/tts`, `WS /ws/voice`.

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
`backend/tools.py`: file read/write/list, shell run (allowlist + timeout, block `rm -rf /`, `format`, etc.), web search (DuckDuckGo free, no key), URL fetch, memory (SQLite `jarvis_memory.db`), reminders (`APScheduler`), open app/URL (`webbrowser`, `os.startfile`).
Expose via `POST /api/tools/*` and as function-calling hints in system prompt.

### 6. UI — "good looking interface"
Dark HUD, Iron-Man arc-reactor canvas, animated waveform, chat bubbles, typing stream, provider/model dropdowns, API-key vault modal, voice button, screen preview, autopilot toggle, command palette (`Ctrl+K`).
Files: `frontend/index.html`, `frontend/styles.css`, `frontend/renderer.js`, `electron/main.js`, `electron/preload.js`.
Must work BOTH as Electron AND as plain browser via `python backend/app.py` → `http://127.0.0.1:8765`.

### 7. Extra imagination (go wild)
- System prompt with personality ("You are Jarvis... witty, loyal, concise").
- Command palette commands: `/screenshot`, `/see`, `/click`, `/type`, `/open`, `/remember`, `/remind`, `/clear`.
- Offline fallback: if no keys at all → Ollama → rule-based canned replies (never blank screen).
- Startup greeting with time, date, system stats.
- Logging + `/api/health`, `/api/providers/status`.

## FILE TREE TO GENERATE
```
PROMPT.md  README.md  LICENSE  .gitignore  .env.example
requirements.txt  package.json
backend/__init__.py  backend/config.py  backend/app.py
backend/providers.py  backend/voice.py  backend/vision_control.py  backend/tools.py
backend/test_opencode_key.py
electron/main.js  electron/preload.js
frontend/index.html  frontend/styles.css  frontend/renderer.js
scripts/start-backend.ps1  scripts/start-all.ps1  scripts/publish-github.ps1
```

## ACCEPTANCE TESTS
1. `pip install -r requirements.txt` succeeds.
2. `python backend/app.py` → `GET /api/health` returns `{"ok": true}`.
3. `python backend/test_opencode_key.py` → uses OpenCode key from auth.json if present, prints masked result, never prints full key.
4. `npm install && npm start` opens HUD; chat works with at least one provider (or offline fallback).
5. Voice button transcribes (browser STT), speaker speaks reply.
6. Screenshot + "what do you see" returns description when a vision model/key is configured.
7. Click test with confirm gate works.

## CONSTRAINTS
- No hardcoded API keys. Mask keys in logs (`sk-...abcd`).
- Minimal deps: `fastapi uvicorn httpx python-dotenv pillow mss pyautogui`. Everything else optional with try/except.
- MIT license.

Build all files now, complete and runnable. No placeholders.
