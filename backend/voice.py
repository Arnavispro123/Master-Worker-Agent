"""Voice: STT + TTS + VAD recorder.

Stack ported from the user's proven RandomStuffOpenCode/jarvis build:
- TTS: edge-tts voice en-GB-RyanNeural, rate +25% (British Jarvis), ffplay playback.
- Capture: sounddevice @16kHz mono int16 + SpeechRecognition Google STT.
- VAD: adaptive ambient calibration, UNLIMITED hear time (120s safety cap),
  stops on ~1.5s silence even with background noise, or on stop phrases
  ("that's all", "done", "stop listening", ...).

All optional deps guarded so import never crashes without a mic.
"""
from __future__ import annotations
import asyncio
import os
import re
import subprocess
import tempfile

# ── user's proven TTS settings ──
TTS_VOICE = os.getenv("JARVIS_TTS_VOICE", "en-GB-RyanNeural")
TTS_RATE = os.getenv("JARVIS_TTS_RATE", "+25%")
TTS_VOLUME = os.getenv("JARVIS_TTS_VOLUME", "+0%")
TTS_PITCH = os.getenv("JARVIS_TTS_PITCH", "+0Hz")

# ── VAD / hear-time settings (no more 10s cap) ──
SAMPLE_RATE = 16000
SILENCE_STOP_S = float(os.getenv("JARVIS_SILENCE_STOP_S", "1.5"))
SAFETY_MAX_S = float(os.getenv("JARVIS_MAX_HEAR_S", "120"))
FRAME_S = 0.1  # 100ms frames

STOP_PHRASES = [
    "that's all", "thats all", "that is all", "that's it", "thats it",
    "i'm done", "im done", "done", "stop listening", "never mind",
    "nevermind", "cancel", "that's enough", "thats enough",
]

_NONWORD = re.compile(r"[^a-z'\s]")


def _norm(text: str) -> str:
    return _NONWORD.sub("", (text or "").lower()).strip()


def contains_stop_phrase(text: str) -> bool:
    t = _norm(text)
    return any(p in t for p in STOP_PHRASES)


def strip_stop_phrase(text: str) -> str:
    """Cut transcript at the first stop phrase so '... that's all bye' -> '...'."""
    t = text or ""
    low = _norm(t)
    cut = len(t)
    for p in STOP_PHRASES:
        i = low.find(p)
        if i != -1:
            # map back approximately: find phrase words in original
            cut = min(cut, i)
    out = t[:cut].strip(" ,.!?;:-").strip()
    return out


# Hesitation sounds that must NEVER end the listen or count as a command.
# "uhhh ... remind me ... hmmm ... at five" -> keep waiting, then run the real part.
FILLERS = {
    "uh", "uhh", "uhhh", "uhhhh", "um", "umm", "ummm",
    "hmm", "hmmm", "hmmmm", "ah", "ahh", "er", "erm", "mmm", "mm",
}


def strip_fillers(text: str) -> str:
    """Remove standalone hesitation tokens; keep everything else verbatim."""
    out: list[str] = []
    for tok in (text or "").split():
        if _norm(tok) not in FILLERS:
            out.append(tok)
    return " ".join(out).strip()


def is_filler_only(text: str) -> bool:
    """True for 'uhhh', 'hmm yeah'... wait, 'yeah' is real. Only pure hesitation."""
    toks = [_norm(t) for t in (text or "").split() if _norm(t)]
    return bool(toks) and all(t in FILLERS for t in toks)


ABORT_ONLY = {"nothing", "never mind", "nevermind", "cancel", "forget it", "forget that"}


def vad_threshold(ambient_rms: float) -> float:
    """Adaptive threshold that survives background noise.

    Fixed 500 breaks in noisy rooms (never stops) or quiet rooms (clips).
    Rule: ambient * 2.5, clamped to [400, 2500].
    """
    try:
        thr = float(ambient_rms) * 2.5
    except Exception:
        thr = 500.0
    return max(400.0, min(2500.0, thr))


def transcribe_file(path: str) -> str:
    # 1. faster-whisper (best, offline)
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(path)
        return " ".join(s.text for s in segments).strip()
    except Exception:
        pass
    # 2. SpeechRecognition (google free) — user's proven path
    try:
        import speech_recognition as sr
        r = sr.Recognizer()
        with sr.AudioFile(path) as src:
            audio = r.record(src)
        return r.recognize_google(audio)
    except Exception as e:
        return f"[stt unavailable: {e}]"


async def _generate_speech(text: str, output_path: str) -> None:
    import edge_tts
    communicate = edge_tts.Communicate(text, TTS_VOICE, rate=TTS_RATE, volume=TTS_VOLUME, pitch=TTS_PITCH)
    await communicate.save(output_path)


def speak(text: str) -> str:
    """Generate mp3 via user's edge-tts settings. Returns path for /api/tts."""
    clean = re.sub(r"<<[^>]+>>", "", text or "").strip()[:800]
    if not clean:
        return ""
    try:
        import edge_tts  # noqa: F401
        out = os.path.join(tempfile.gettempdir(), "jarvis_tts.mp3")
        asyncio.run(_generate_speech(clean, out))
        return out
    except Exception:
        pass
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.say(clean)
        engine.runAndWait()
        return "spoken-locally"
    except Exception as e:
        return f"[tts unavailable: {e}]"


def speak_local(text: str, play: bool = True) -> str:
    """Blocking Jarvis-style speak: print + edge-tts + ffplay (user's exact flow).
    In Electron the HUD owns the speakers (JARVIS_BACKEND_VOICE=0) so the backend
    stays silent — no double voice / mic echo wars with the orb."""
    clean = re.sub(r"<<[^>]+>>", "", text or "").strip()
    if clean:
        print(f"\n  JARVIS: {clean}")
    if not clean:
        return ""
    if play and os.getenv("JARVIS_BACKEND_VOICE", "1") == "0":
        return "muted-hud-owns-voice"
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            tmp_path = tmp.name
        asyncio.run(_generate_speech(clean, tmp_path))
        if play:
            try:
                subprocess.run(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", tmp_path],
                    timeout=90, capture_output=True,
                )
            except Exception:
                pass
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return "spoken"
    except Exception as e:
        return f"[tts unavailable: {e}]"


def calibrate_ambient(duration_s: float = 1.0) -> float:
    """Measure room noise floor RMS so the threshold adapts to background noise."""
    try:
        import sounddevice as sd
        import numpy as np
        n = int(SAMPLE_RATE * duration_s)
        audio = sd.rec(n, samplerate=SAMPLE_RATE, channels=1, dtype="int16")
        sd.wait()
        chunk = np.frombuffer(audio.tobytes(), dtype=np.int16).astype(float)
        rms = float(np.sqrt(max(1e-9, np.mean(chunk ** 2))))
        return rms
    except Exception:
        return 500.0


def record_until_silence(
    timeout: float | None = None,
    max_duration: float = SAFETY_MAX_S,
    silence_stop: float = SILENCE_STOP_S,
    calibrate_s: float = 0.8,
    threshold: float | None = None,
) -> "object | None":
    """Record while the user speaks — unlimited hear time.

    Stops when: (a) ~silence_stop seconds of quiet even with background noise
    (adaptive threshold), (b) max_duration safety cap (default 120s),
    (c) timeout with no speech at all (wake-listening idle) -> None.
    Returns SpeechRecognition AudioData or None.
    """
    import sounddevice as sd
    import numpy as np
    import speech_recognition as sr

    frame_size = int(SAMPLE_RATE * FRAME_S)
    max_silence_frames = max(1, int(silence_stop / FRAME_S))
    max_frames = int(max_duration / FRAME_S)

    if threshold is None:
        ambient = calibrate_ambient(calibrate_s) if calibrate_s > 0 else 500.0
        threshold = vad_threshold(ambient)

    frames: list = []
    stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    stream.start()
    silence_count = 0
    started = False
    total = 0
    try:
        while total < max_frames:
            data, _ = stream.read(frame_size)
            chunk = np.frombuffer(data, dtype=np.int16)
            rms = float(np.sqrt(max(0.0, np.mean(chunk.astype(float) ** 2))))
            total += 1
            if rms > threshold:
                frames.append(chunk)
                silence_count = 0
                started = True
            elif started:
                frames.append(chunk)  # keep trailing pause for natural cut
                silence_count += 1
                if silence_count >= max_silence_frames:
                    break
            else:
                if timeout and total * FRAME_S > timeout:
                    return None
    finally:
        try:
            stream.stop()
        except Exception:
            pass
    if not frames:
        return None
    audio = np.concatenate(frames).astype(np.int16).tobytes()
    return sr.AudioData(audio, SAMPLE_RATE, 2)
