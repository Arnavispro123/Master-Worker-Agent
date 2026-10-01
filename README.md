# J.A.R.V.I.S. — Just A Rather Very Intelligent System

Local-first AI assistant with **voice, vision, screen control, agents and web research** — wrapped in an Iron-Man HUD with a voice-reactive orb that lives on your desktop. Works **free or paid**: bring any API key, or run fully local.

![stack](https://img.shields.io/badge/Electron-HUD-blue) ![backend](https://img.shields.io/badge/FastAPI-Python-green) ![voice](https://img.shields.io/badge/voice-wake%20word-red) ![license](https://img.shields.io/badge/license-MIT-lightgrey)

> Built from `PROMPT.md` — the master prompt. Paste it into any AI coder to rebuild this repo.

## ✨ Features
- **AI router with auto-fallback:** OpenCode Zen → OpenRouter (free models) → Groq (free) → Gemini (free) → Ollama (local) → OpenAI / Anthropic (paid). Missing keys are skipped, never crash.
- **Voice:** wake word *"jarvis"* (backend ears work with the tab closed), unlimited hear time, adaptive noise threshold, filler-tolerant (*"uhhh"* never aborts), stop phrases (*"that's all"*), British male TTS with TTS file caching.
- **Orb overlay:** draggable glowing orb with voice-reactive radius + dancing beats ring, radiating waves, live status. Rests where you put it (8-zone first-run picker). System-tray background mode.
- **Vision:** one-click screenshot → *"what do you see?"* with any vision model.
- **Control:** AI moves/clicks/types/scrolls with a confirm gate (autopilot toggle for full auto).
- **Agents:** *"do: organize my downloads"* — thinks, runs shell/files/web tools, shows its trace.
- **Research:** *"research black holes"* goes online, reads real articles, answers with clickable sources — and can save findings to a desktop folder.
- **Instant answers, no AI needed:** time/date, opening apps & sites (*"open youtube"*), reminders, notes, jokes, calculator.
- **Preferences + model cache** persist across restarts. Keys live only in local `.env`, masked everywhere.

## 🚀 Install (anyone, ~5 minutes)

**1. Prerequisites**
- [Python 3.10+](https://www.python.org/downloads/) (tick *Add to PATH*)
- A microphone (laptop mic is fine)
- Optional: [Node.js 18+](https://nodejs.org) for the desktop app (tray + orb), [ffmpeg](https://ffmpeg.org/download.html) for out-loud voice (`ffplay`)

**2. Get the code**
```powershell
git clone https://github.com/Arnavispro123/Master-Worker-Agent.git Jarvis
cd Jarvis
```

**3. Run it — one command does everything**
```powershell
python main.py
```
This installs Python deps, creates `.env`, starts the backend, opens the HUD at `http://127.0.0.1:8765`, and launches the Electron desktop app if `npm install` was run once. That is the whole setup.

**4. Add a brain (free)** — click **Keys** in the top bar, paste one:
| Key | Cost | Get it |
|---|---|---|
| Groq | ✅ free, fast | https://console.groq.com/keys |
| Gemini | ✅ free | https://aistudio.google.com/apikey |
| OpenRouter | ✅ free models | https://openrouter.ai/keys |
| Ollama | ✅ local, no key | https://ollama.com → `ollama run llama3.1` |
| OpenCode | uses your login | auto-detected (needs billing enabled) |
| OpenAI / Anthropic | paid | their dashboards |

Models refresh live per provider. No keys at all? Jarvis still opens with local clock/tools + offline fallback.

**5. Talk to it** — sidebar → **Wake word: on** (pick *this window* or *backend* ears), say *"jarvis, what time is it"*. Hit **test mic** if it ever ignores you — it reports exactly what it hears.

## 🖥️ Everyday use
- **Chat:** ask anything; `/agent <goal>` runs tools itself, `/research <topic>` reads the web, `/see` describes your screen, `/click <thing>`, `/search`, `/screenshot`, `/remember`, `/remind`.
- **Voice:** Talk button (push-to-talk), wake word toggle, voice-replies toggle. `Alt+J` talks, `Ctrl+K` commands.
- **Orb:** drag it anywhere (position saves). Click it to open the HUD. Tray icon → Show / Move orb / Quit. Closing the window hides to tray — wake keeps hearing.
- Flags: `python main.py --setup-only | --no-browser | --electron | --port 9000`.

## 🔧 Troubleshooting
| Symptom | Fix |
|---|---|
| Keys modal empty / save "fails" | Backend isn't running → `python main.py`. Nothing is lost; `.env` is untouched. Hard-refresh the page (Ctrl+Shift+R) after updates. |
| Wake hears nothing | Sidebar → **test mic**. Silent → raise mic level / plug mic. Clipping → lower level, disable Mic Boost. Wrong mic → `JARVIS_MIC_DEVICE` (index or name) in `.env`. Mic blocked → allow it in the browser site settings. |
| Groq `429 rate-limited` | Free-tier limit — wait a minute or switch provider in the dropdown. Clock/open/research still work (no AI needed). |
| Voice replies silent | Needs `ffplay` (ffmpeg) for backend voice, else browser voice fallback. Check volume + voice-replies toggle. |
| `npm start` fails | Install Node.js, run `npm install` once. Or skip it — `python main.py` browser HUD does everything except tray/orb. |
| Orb stuck / doubles | Quit fully from tray (not just close), restart. Single-instance lock prevents twins. |

## 📁 Structure
```
main.py  PROMPT.md  README.md  requirements.txt  package.json
backend/  app.py providers.py agent.py research.py opener.py fastpath.py
          voice.py wake.py vision_control.py tools.py prefs.py activity.py config.py
frontend/ index.html styles.css renderer.js orb.html place.html
electron/ main.js preload.js tray.png
```

## 🛡️ Safety & privacy
- Autopilot OFF by default; AI clicks need your confirm. Shell blocks dangerous commands. File deletes refuse home/Desktop roots.
- API keys stay in local `.env` (gitignored), masked in UI/logs, never committed. `preferences.json` / `models_cache.json` are local caches, also ignored.

## 🤝 Contributing
PRs welcome — especially new providers, tools for the agent, and UI polish. Run a quick `python -m py_compile backend/*.py` and `node --check frontend/renderer.js` before pushing.

MIT — go build your suit. 🦾
