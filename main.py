#!/usr/bin/env python3
"""JARVIS one-click launcher for a brand-new person.

Just:  python main.py
Does: checks python → pip installs requirements → creates .env →
starts backend → opens HUD in browser → (optionally) starts Electron.

Flags: --setup-only (install, don't run)  --no-browser  --electron  --port 8765
Electron (tray+orb) starts automatically when npm + node_modules exist.
"""
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQ = ROOT / "requirements.txt"
ENV_EX = ROOT / ".env.example"
ENV = ROOT / ".env"
PORT = int(os.getenv("JARVIS_PORT", "8765"))
for a in sys.argv[1:]:
    if a.startswith("--port"):
        PORT = int(a.split("=")[-1] if "=" in a else sys.argv[sys.argv.index(a) + 1])

def run(cmd, **kw):
    print("»", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, **kw)

def ensure_env():
    if not ENV.exists() and ENV_EX.exists():
        shutil.copy(ENV_EX, ENV)
        print("created .env — paste keys in the app via 🔑 (or edit .env)")
    # ensure port line
    try:
        txt = ENV.read_text() if ENV.exists() else ""
        if "JARVIS_PORT" not in txt:
            with open(ENV, "a") as f:
                f.write(f"\nJARVIS_PORT={PORT}\n")
    except Exception:
        pass

def ensure_python_deps():
    print("== python deps ==")
    run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    run([sys.executable, "-m", "pip", "install", "-r", str(REQ)])

def backend_wait(url, timeout=40):
    import urllib.request
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False

def find_npm():
    """npm on Windows is npm.cmd — plain subprocess can't see it. Returns argv or None."""
    import shutil
    for cand in ("npm.cmd", "npm"):
        p = shutil.which(cand)
        if p:
            return [p]
    for guess in (r"C:\Program Files\nodejs\npm.cmd",
                  os.path.expandvars(r"%APPDATA%\npm\npm.cmd")):
        if os.path.exists(guess):
            return [guess]
    return None


def main():
    print(r"""
     J A R V I S  — one-click setup
    """)
    if sys.version_info < (3, 10):
        sys.exit("need Python 3.10+ — https://python.org/downloads")
    ensure_env()
    ensure_python_deps()
    if "--setup-only" in sys.argv:
        print("setup done. run: python main.py")
        return
    print("== starting backend ==")
    env = dict(os.environ, JARVIS_PORT=str(PORT))
    try:
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app:app",
                                 "--host", "127.0.0.1", "--port", str(PORT)], cwd=str(ROOT), env=env)
    except Exception as e:
        sys.exit(f"could not start backend: {e}\nTry: pip install -r requirements.txt")
    url = f"http://127.0.0.1:{PORT}"
    if not backend_wait(url):
        try:
            proc.terminate()
        except Exception:
            pass
        sys.exit("backend failed to start — see errors above. Try: python backend/app.py")
    print(f"JARVIS online at {url}")
    if "--no-browser" not in sys.argv and "--electron" not in sys.argv:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    # Electron HUD (tray + orb) if available — it reuses THIS backend, no second one
    npm = find_npm()
    if (ROOT / "node_modules").exists() and npm:
        print("starting Electron HUD… (Ctrl+C quits everything)")
        try:
            run([*npm, "start"], cwd=str(ROOT))
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"Electron failed ({e}) — browser HUD at {url} still works.")
            _wait_forever(proc)
    elif "--electron" in sys.argv:
        print("Electron asked for but not ready:",
              "npm missing — install Node.js from https://nodejs.org" if not npm
              else "run `npm install` once first.")
        print(f"Browser HUD at {url} works fine meanwhile.")
        _wait_forever(proc)
    else:
        print("Tip: `npm install` once, then `python main.py` also opens the desktop HUD.")
        print("Backend running. Ctrl+C to quit.")
        _wait_forever(proc)
    try:
        proc.terminate()
    except Exception:
        pass


def _wait_forever(proc):
    try:
        proc.wait()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
