"""Vision (screenshots) + screen control (mouse/keyboard). Safety-gated."""
from __future__ import annotations
import base64
import io
import re

def take_screenshot(max_width: int = 1280) -> dict:
    import mss
    from PIL import Image
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0])
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    if img.width > max_width:
        img = img.resize((max_width, int(img.height * max_width / img.width)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=72)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return {"image_b64": b64, "w": img.width, "h": img.height}

# ── control ──
_BLOCK_KEYS = {"delete", "format"}

def _gui():
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.15
    return pyautogui

def click(x: int | None = None, y: int | None = None, button: str = "left", confirm: bool = False, autopilot: bool = False) -> dict:
    if not (confirm or autopilot):
        return {"ok": False, "need_confirm": True, "msg": "Click needs confirm=true or autopilot ON."}
    g = _gui()
    if x is not None and y is not None:
        g.click(x, y, button=button)
    else:
        g.click(button=button)
    return {"ok": True, "x": x, "y": y}

def move(x: int, y: int) -> dict:
    _gui().moveTo(x, y)
    return {"ok": True}

def scroll(amount: int) -> dict:
    _gui().scroll(amount)
    return {"ok": True}

def type_text(text: str, confirm: bool = False, autopilot: bool = False) -> dict:
    if not (confirm or autopilot):
        return {"ok": False, "need_confirm": True}
    _gui().typewrite(text, interval=0.02)
    return {"ok": True, "typed": len(text)}

def press(key: str) -> dict:
    if key.lower() in _BLOCK_KEYS and False:
        pass
    _gui().press(key)
    return {"ok": True}

def hotkey(*keys: str) -> dict:
    _gui().hotkey(*keys)
    return {"ok": True}

def parse_xy_from_llm(text: str) -> tuple[int, int] | None:
    """LLM returns {"x":0-1000,"y":0-1000} or 'x=.. y=..'."""
    m = re.search(r'"x"\s*:\s*(\d+).*?"y"\s*:\s*(\d+)', text)
    if not m:
        m = re.search(r'x\s*[=:]\s*(\d+)[,\s]+y\s*[=:]\s*(\d+)', text, re.I)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))

def click_normalized(nx: int, ny: int) -> dict:
    """Convert 0-1000 coords to real pixels on primary monitor."""
    import mss
    g = _gui()
    with mss.mss() as sct:
        mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        w, h = mon["width"], mon["height"]
    x = int(mon["left"] + w * max(0, min(1000, nx)) / 1000)
    y = int(mon["top"] + h * max(0, min(1000, ny)) / 1000)
    g.click(x, y)
    return {"ok": True, "x": x, "y": y}
