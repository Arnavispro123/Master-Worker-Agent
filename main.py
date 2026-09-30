#!/usr/bin/env python3
"""JARVIS one-click launcher for a brand-new person.

Just:  python main.py
Does: checks python → pip installs requirements → creates .env →
starts backend → opens HUD in browser → (optionally) starts Electron.

Flags: --setup-only (install, don't run)  --no-browser  --port 8765
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
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app:app",
                             "--host", "127.0.0.1", "--port", str(PORT)], cwd=str(ROOT), env=env)
    url = f"http://127.0.0.1:{PORT}"
    if backend_wait(url):
        print(f"JARVIS online at {url}")
        if "--no-browser" not in sys.argv:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        # try electron HUD if node_modules present
        if (ROOT / "node_modules" / ".bin").exists() or (ROOT / "node_modules").exists():
            print("starting Electron HUD… (Ctrl+C quits everything)")
            try:
                run(["npm", "start"], cwd=str(ROOT))
            except KeyboardInterrupt:
                pass
        else:
            print("Tip: npm install && npm start  → prettier desktop HUD")
            print("Backend running. Ctrl+C to quit.")
            try:
                proc.wait()
            except KeyboardInterrupt:
                pass
    else:
        print("backend failed to start — see errors above. Try: python backend/app.py")
    try:
        proc.terminate()
    except Exception:
        pass

if __name__ == "__main__":
    main()
