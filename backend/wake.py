"""Wake-word listener built on the user's proven stack.

Proven in RandomStuffOpenCode/jarvis: sounddevice capture @16kHz +
SpeechRecognition Google STT + edge-TTS replies — no API keys needed
for voice itself (Google web STT + edge-tts are keyless).

Changes vs the old prototype:
- REMOVED the 10s hear cap. Command capture is unlimited: it keeps
  listening while the user speaks (up to a 120s safety cap) and stops
  after ~1.5s of silence, with an adaptive noise-floor threshold so
  background noise doesn't keep it open forever.
- ALSO stops early if the user says "that's all" / "done" /
  "stop listening" etc. (see voice.STOP_PHRASES).
- SETTLE: after hearing "jarvis", waits ~1s for you to keep speaking
  and merges "jarvis ... whats the time" into one command. "Yes, Sir?"
  is only spoken when you REALLY stopped after the wake word — never
  as an interruption. When a command follows the wake word, Jarvis
  goes straight to the answer (the answer itself is the acknowledgement).
- NO COUNTDOWN after "Yes, Sir?": the follow-up listen waits forever
  (each utterance still ends on silence / safety cap / stop phrase).
  Hesitation ("uhhh", "hmmm", long pauses) never aborts it — fillers
  are skipped and "...and also..." continuations are merged.
- Same HTTP API as before: start/stop/status/poll (+ on_command hook
  so main.py / app.py can execute commands as they arrive).
"""
from __future__ import annotations
import os
import queue
import re
import threading
import time
from typing import Callable

from . import voice as voice_mod

# How long to keep the mic open after "jarvis" for you to keep talking.
SETTLE_S = float(os.getenv("JARVIS_WAKE_SETTLE_S", "1.0"))

STATE = {
    "running": False,
    "heard": 0,
    "commands": 0,
    "engine": "none",
    "error": "",
    "words": ["jarvis", "hey jarvis", "computer"],
    "hear": (f"unlimited (safety {voice_mod.SAFETY_MAX_S:g}s, silence-stop "
             f"{voice_mod.SILENCE_STOP_S:g}s, settle {SETTLE_S:g}s, adaptive VAD)"),
}
_thread: threading.Thread | None = None
_events: queue.Queue = queue.Queue()
_on_command: Callable[[str], None] | None = None


def set_on_command(fn: Callable[[str], None] | None) -> None:
    global _on_command
    _on_command = fn


def status() -> dict:
    d = dict(STATE)
    d["queued"] = _events.qsize()
    return d


def _push(kind: str, text: str = "") -> None:
    if kind == "wake":
        STATE["heard"] += 1
    elif kind == "command":
        STATE["commands"] += 1
    try:
        _events.put_nowait({"kind": kind, "wake": kind == "wake", "text": text, "n": STATE["heard"]})
    except Exception:
        pass


def _strip_wake(text: str, words: list[str]) -> str:
    low = text.lower().strip()
    for w in sorted(words, key=len, reverse=True):
        i = low.find(w)
        if i != -1:
            cmd = text[i + len(w):].strip()
            return re.sub(r"^[,\s.!?]+", "", cmd)
    return ""


def _loop(words: list[str]) -> None:
    try:
        import speech_recognition as sr
        import sounddevice as sd
    except Exception as e:
        STATE["error"] = f"voice deps missing ({e}). pip install SpeechRecognition sounddevice soundfile numpy"
        STATE["running"] = False
        return
    try:
        devices = sd.query_devices()
        di = sd.default.device[0]
        print(f"  [Voice] mic: {devices[di]['name']}")
    except Exception as e:
        STATE["error"] = f"no microphone ({e})"
        STATE["running"] = False
        return

    r = sr.Recognizer()
    STATE["engine"] = "sounddevice+google(unlimited-hear+settle)"
    STATE["error"] = ""
    print(f"  [Voice] always-listening. Say 'Jarvis' + command. Unlimited hear; {SETTLE_S:g}s settle so I never cut you off.")

    while STATE["running"]:
        try:
            # 1) idle wake snippet (short; returns None on quiet timeout)
            audio = voice_mod.record_until_silence(timeout=5, max_duration=8, calibrate_s=0)
            if audio is None or not STATE["running"]:
                continue
            try:
                text = r.recognize_google(audio)
            except sr.UnknownValueError:
                continue
            except Exception:
                time.sleep(0.3)
                continue
            low = text.lower().strip()
            if not any(w in low for w in words):
                continue

            cmd = _strip_wake(text, words)
            # ── SETTLE (~1s): don't answer yet — user may still be talking.
            # "jarvis whats the time" arrives either whole in `text` or split
            # across `text` + trailing speech. Merge before deciding anything,
            # so we never blurt "Yes, Sir?" over the command.
            tail = voice_mod.record_until_silence(
                timeout=SETTLE_S, max_duration=voice_mod.SAFETY_MAX_S, calibrate_s=0)
            if tail is not None:
                try:
                    extra = r.recognize_google(tail).strip()
                    if extra:
                        extra_cmd = _strip_wake(extra, words) or extra
                        if cmd and extra_cmd and extra_cmd.lower() not in cmd.lower():
                            cmd = f"{cmd} {extra_cmd}"
                        elif not cmd:
                            cmd = extra_cmd
                except sr.UnknownValueError:
                    pass
                except Exception:
                    pass

            if not cmd:
                # Genuine wake-only: user really stopped after "jarvis".
                # NOW it's safe to invite without interrupting — then wait
                # PATIENTLY (no countdown): hesitation ("uhhh", "hmmm",
                # long pauses) never aborts the listen.
                voice_mod.speak_local("Yes, Sir?", play=True)
                parts: list[str] = []
                while STATE["running"]:
                    # timeout=None: wait forever for speech; each utterance
                    # still ends on silence-stop / safety cap / stop phrase.
                    audio2 = voice_mod.record_until_silence(timeout=None, calibrate_s=0.4)
                    if audio2 is None or not STATE["running"]:
                        continue
                    try:
                        chunk = r.recognize_google(audio2).strip()
                    except sr.UnknownValueError:
                        continue  # mumble — keep waiting silently, don't nag
                    except Exception:
                        time.sleep(0.3)
                        continue
                    if not chunk:
                        continue
                    # our own "Yes, Sir?" invite echoing back via speakers — ignore it
                    if chunk.lower().strip().rstrip(".,!?") in ("yes sir", "yes sirs", "yes", "sir"):
                        continue
                    if chunk.lower().strip() in voice_mod.ABORT_ONLY:
                        cmd = ""
                        break
                    if voice_mod.contains_stop_phrase(chunk):
                        chunk = voice_mod.strip_stop_phrase(chunk)
                        if chunk and not voice_mod.is_filler_only(chunk):
                            parts.append(voice_mod.strip_fillers(chunk) or chunk)
                        break
                    if voice_mod.is_filler_only(chunk):
                        continue  # pure "uhhh/hmmm" — keep waiting
                    clean = voice_mod.strip_fillers(chunk) or chunk
                    parts.append(clean)
                    # continuation settle: user may pause then add
                    # "...and also ..." — merge up to 3 more utterances.
                    for _ in range(3):
                        tail2 = voice_mod.record_until_silence(
                            timeout=2.0, max_duration=voice_mod.SAFETY_MAX_S, calibrate_s=0)
                        if tail2 is None:
                            break
                        try:
                            more = r.recognize_google(tail2).strip()
                        except Exception:
                            break
                        if not more or voice_mod.is_filler_only(more):
                            continue
                        if more.lower().strip() in voice_mod.ABORT_ONLY:
                            break
                        if voice_mod.contains_stop_phrase(more):
                            more = voice_mod.strip_stop_phrase(more)
                            if more:
                                parts.append(voice_mod.strip_fillers(more) or more)
                            break
                        parts.append(voice_mod.strip_fillers(more) or more)
                    break
                cmd = " ".join(parts).strip()

            # stop-phrase: "remind me ... that's all" -> cut before it
            if voice_mod.contains_stop_phrase(cmd):
                cmd = voice_mod.strip_stop_phrase(cmd)

            cmd = cmd.strip()
            if not cmd:
                continue
            print(f"\n  [voice command: {cmd}]")
            _push("wake", cmd)
            _push("command", cmd)
            if _on_command:
                try:
                    _on_command(cmd)
                except Exception as e:
                    print(f"  [voice command error: {e}]")
        except Exception:
            time.sleep(0.5)
            continue


def start(words: list[str] | None = None) -> dict:
    global _thread
    if STATE["running"]:
        return status()
    STATE["words"] = words or STATE["words"]
    STATE["running"] = True
    STATE["error"] = ""
    STATE["engine"] = "sounddevice+google(starting)"
    _thread = threading.Thread(target=_loop, args=(STATE["words"],), daemon=True)
    _thread.start()
    return status()


def stop() -> dict:
    STATE["running"] = False
    STATE["engine"] = "none"
    return status()


def poll() -> dict:
    hits = []
    try:
        while True:
            hits.append(_events.get_nowait())
    except Exception:
        pass
    return {"hits": hits, "state": status()}
