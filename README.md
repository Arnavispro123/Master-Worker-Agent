# J.A.R.V.I.S. — Just A Rather Very Intelligent System

Local-first AI assistant with **voice, vision, screen control**, and a beautiful Iron-Man HUD.
Works **free or paid** — bring any API key, or run fully local.

![stack](https://img.shields.io/badge/Electron-HUD-blue) ![backend](https://img.shields.io/badge/FastAPI-Python-green) ![license](https://img.shields.io/badge/license-MIT-lightgrey)

> Built from `PROMPT.md` — that file is the master prompt. Paste it into any AI coder to rebuild this repo.

## ✨ Features
- **AI Router (auto-fallback):** OpenCode Zen (use your OpenCode login key to test free!) → OpenRouter free → Groq free → Gemini free → Ollama local → OpenAI / Anthropic paid
- **Voice:** push-to-talk + wake-word "jarvis", browser STT (free) + backend Whisper, browser TTS + edge-tts
- **Vision:** one-click screenshot → ask "what do you see?" with any vision model
- **Control:** AI can move/click/type/scroll with a safety confirm gate + autopilot toggle
- **Tools:** files, shell (sandboxed), web search (free, no key), URL fetch, memory (SQLite), reminders, open apps
- **HUD:** arc reactor, waveform, streaming chat, provider picker, key vault, screen preview, command palette (`Ctrl+K`)

## 🚀 Quick start
```powershell
# 1. backend
pip install -r requirements.txt
copy .env.example .env   # paste keys
python backend/app.py    # → http://127.0.0.1:8765  (also serves the HUD in browser)

# 2. desktop app (optional, prettier)
npm install
npm start
```

Test your OpenCode key (no key printed, ever):
```powershell
python backend/test_opencode_key.py
```

## 🔑 Keys (.env)
| Key | Free? | Get it |
|---|---|---|
| `OPENCODE_API_KEY` | ✅ uses your OpenCode auth | auto-loaded from `~/.local/share/opencode/auth.json` |
| `OPENROUTER_API_KEY` | ✅ free models | https://openrouter.ai |
| `GROQ_API_KEY` | ✅ free | https://console.groq.com |
| `GEMINI_API_KEY` | ✅ free | https://aistudio.google.com |
| `OLLAMA_BASE_URL` | ✅ local, no key | https://ollama.com |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | paid | their dashboards |

No keys at all? Jarvis still opens and replies via Ollama → offline fallback. You will never see a blank screen.

## 🖥️ Commands in chat
`/screenshot` `/see <question>` `/click <what>` `/type <text>` `/open <app|url>` `/remember <fact>` `/remind <in 10m> <msg>` `/clear`

## 🛡️ Safety
- Autopilot OFF by default. Every AI click needs your Confirm unless you set `JARVIS_DANGER_AUTOPILOT=1`.
- Shell blocks `rm -rf /`, `format`, registry edits, etc. Keys are masked in logs.

## 📁 Structure
```
backend/  config.py app.py providers.py voice.py vision_control.py tools.py
frontend/ index.html styles.css renderer.js
electron/ main.js preload.js
scripts/  publish-github.ps1
PROMPT.md README.md
```

## 📤 Publish to GitHub
```powershell
.\scripts\publish-github.ps1 -RepoUrl "https://github.com/YOU/jarvis.git"
```
No git installed? The script tells you the one-line `winget install Git.Git` fix.

MIT — go build your suit. 🦾
