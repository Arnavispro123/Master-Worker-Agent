/* JARVIS renderer — chat + agent + live models + offline wake-word + voice */
const API = (window.jarvisAPI && window.jarvisAPI.base) || "http://127.0.0.1:8765";
const $ = id => document.getElementById(id);
const chat = $("chat"), form = $("form"), input = $("input");
let history = [], voiceOn = true, withShot = false;
let _sendAbort = null, _lastSend = { text: "", t: 0 };
/* Electron's Chromium has no Google speech key, so Web Speech silently fails
   there — use mic→WAV→backend-STT instead. Browsers keep Web Speech. */
const IS_ELECTRON = !!(window.jarvisAPI && window.jarvisAPI.isElectron);
let _micLevel = null; // live mic RMS → wave meter while recording
const PROVIDERS = ["opencode", "openrouter", "groq", "gemini", "ollama", "openai", "anthropic"];
const KEYMAP = { opencode: "OPENCODE_API_KEY", openrouter: "OPENROUTER_API_KEY", groq: "GROQ_API_KEY", gemini: "GEMINI_API_KEY", openai: "OPENAI_API_KEY", anthropic: "ANTHROPIC_API_KEY", ollama: null };
const LINKS = { opencode: "https://opencode.ai/auth", openrouter: "https://openrouter.ai/keys", groq: "https://console.groq.com/keys", gemini: "https://aistudio.google.com/apikey", openai: "https://platform.openai.com/api-keys", anthropic: "https://console.anthropic.com/", ollama: "https://ollama.com/download" };

/* reactor + waveform */
const rc = $("reactor").getContext("2d");
let t = 0;
(function reactor() {
  t += 0.02; rc.clearRect(0, 0, 300, 300);
  rc.save(); rc.translate(150, 150);
  for (let i = 0; i < 3; i++) {
    rc.beginPath(); rc.arc(0, 0, 40 + i * 28 + Math.sin(t + i) * 4, 0, 7);
    rc.strokeStyle = `rgba(53,224,255,${0.7 - i * 0.18})`; rc.lineWidth = 3 + i; rc.stroke();
    for (let k = 0; k < 10; k++) {
      const a = t * (i + 1) + k * 0.628;
      rc.fillStyle = "#bff3ff";
      rc.fillRect(Math.cos(a) * (40 + i * 28), Math.sin(a) * (40 + i * 28), 3, 3);
    }
  }
  rc.beginPath(); rc.arc(0, 0, 26, 0, 7); rc.fillStyle = "#dffaff"; rc.fill();
  rc.restore(); requestAnimationFrame(reactor);
})();
const wv = $("wave").getContext("2d");
function wave(level = 0.15) {
  wv.clearRect(0, 0, 300, 64); wv.strokeStyle = "#35e0ff"; wv.beginPath();
  for (let x = 0; x < 300; x += 2) {
    const amp = (_micLevel != null ? Math.min(1, _micLevel * 9) : level);
    const y = 32 + Math.sin(x * 0.15 + Date.now() / 200) * 20 * amp * (0.5 + Math.random());
    x ? wv.lineTo(x, y) : wv.moveTo(x, y);
  }
  wv.stroke(); requestAnimationFrame(() => wave(level));
}
wave();

function toast(m) { const e = $("toast"); e.textContent = m; e.style.display = "block"; setTimeout(() => e.style.display = "none", 3000); }
/* HUD → orb bridge. Two lanes, both best-effort:
   Electron IPC (instant, levels included) + backend activity bus (works from
   ANY window — browser tab, second HUD, headless). */
function NOTE(kind, text) {
  const t = String(text || "").slice(0, 140);
  try { if (window.jarvisAPI && window.jarvisAPI.notify) window.jarvisAPI.notify(kind, text); } catch {}
  if (kind === "level") return; // IPC-only, too chatty for HTTP
  try {
    fetch(API + "/api/activity", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind, text: t }) }).catch(() => {});
  } catch {}
}
/* rich chat rendering: linkified sources + collapsible agent trace */
function richBody(shown) {
  let main = String(shown || ""), trace = "";
  for (const sep of ["— agent trace —", "— trace —"]) {
    const i = main.indexOf(sep);
    if (i !== -1) { trace = main.slice(i + sep.length).trim(); main = main.slice(0, i).trim(); break; }
  }
  let html = esc(main).replace(/\n/g, "<br>");
  html = html.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
  let out = `<div>${html}</div>`;
  if (trace) {
    const rows = trace.split(/\n+/).map(s => s.trim()).filter(Boolean);
    const n = rows.filter(s => /^step \d+/i.test(s)).length;
    const lis = rows.map(s => `<li>${esc(s.replace(/^step \d+:\s*/i, ""))}</li>`).join("");
    out += `<details class="trace"><summary>Agent trace${n ? ` (${n} steps)` : ""}</summary><ol>${lis}</ol></details>`;
  }
  return out;
}
function esc(s) { return String(s).replace(/</g, "&lt;"); }
/* speakable: what the voice is ALLOWED to read. Traces, JSON, URLs, code
   and tags stay on screen only — never spoken. */
function speakable(text) {
  let s = String(text || "");
  s = s.split("— agent trace —")[0].split("— trace —")[0];
  s = s.replace(/```[\s\S]*?```/g, " ");
  s = s.replace(/<<[^>]+>>/g, " ");
  s = s.replace(/https?:\/\/\S+/g, " link ");
  s = s.replace(/www\.\S+/g, " link ");
  s = s.replace(/[\{\}\[\]\"\\*_`#<>|]/g, " ");
  s = s.replace(/\s+/g, " ").trim();
  s = s.replace(/(link\s*){2,}/g, "link ");
  return s.slice(0, 600);
}
function addMsg(who, text, meta = "", img = "") {
  const d = document.createElement("div");
  d.className = "msg " + (who === "you" ? "user" : "jarvis");
  d._fullText = String(text);
  d.innerHTML = `<div>${esc(text)}</div>${img ? `<img src="${img}"/>` : ""}${meta ? `<div class="meta">${esc(meta)}</div>` : ""}` +
    (who === "you" ? "" : `<div class="actions"><button data-act="replay" title="Replay voice">Replay</button><button data-act="copy" title="Copy text">Copy</button><button data-act="stop" title="Stop voice / stop run">Stop</button></div>`);
  chat.appendChild(d); chat.scrollTop = 1e6; return d;
}
function stopAllSound() {
  _voicing = false;
  NOTE("idle");
  try { speechSynthesis.cancel(); } catch { }
  try { if (_audioEl) _audioEl.pause(); } catch { }
  try { if (_sendAbort) _sendAbort.abort(); } catch { }
}
chat.addEventListener("click", async e => {
  const c = e.target.closest("[data-confirm-click]");
  if (c) {
    c.disabled = true; c.textContent = "…";
    try {
      const r = await (await fetch(API + "/api/agent/click-target", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction: c.dataset.instruction || "", provider: $("provider").value, model: $("model").value || null, confirm: true })
      })).json();
      toast(r.ok ? ("clicked. " + (r.say || "")) : ("failed: " + (r.error || r.say || "?")));
      c.textContent = r.ok ? "done" : "failed";
    } catch (err) { c.textContent = "error"; }
    return;
  }
  const b = e.target.closest("[data-act]");
  if (!b) return;
  const bubble = b.closest(".msg");
  const txt = (bubble && bubble._fullText) || "";
  if (b.dataset.act === "replay") speak(txt);
  else if (b.dataset.act === "copy") {
    try { await navigator.clipboard.writeText(txt); toast("copied"); }
    catch { toast("copy failed"); }
  }
  else if (b.dataset.act === "stop") { stopAllSound(); toast("stopped"); }
});
async function health() {
  try {
    const r = await (await fetch(API + "/api/health")).json();
    $("status").textContent = `online • ${new Date().toLocaleTimeString()} • autopilot ${r.autopilot ? "ON" : "OFF"} • ears ${wakeOn ? earsLive : "off"}`;
  } catch { $("status").textContent = "backend offline — run: python main.py"; }
}
setInterval(health, 5000); health();

/* ── live models ── */
async function loadModels(provider, force = false) {
  const sel = $("model");
  sel.innerHTML = `<option value="">loading…</option>`;
  try {
    const r = await (await fetch(`${API}/api/providers/models?provider=${provider}&force=${force}`)).json();
    const models = r.models || [];
    sel.innerHTML = `<option value="">auto model${r.live ? ` (${models.length} live)` : " (curated)"}</option>` +
      models.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join("");
  } catch {
    sel.innerHTML = `<option value="">backend offline — start it first</option>`;
    toast("Backend offline — run: python main.py (or npm start)");
  }
}
$("provider").onchange = e => { loadModels(e.target.value); savePrefs(); };
$("model").onchange = () => savePrefs();
loadModels("auto");

/* ── keys modal with per-provider live models + test ── */
function buildKeyRows(status = {}) {
  $("keyRows").innerHTML = PROVIDERS.map(p => {
    const s = status[p] || {};
    return `<div class="keyrow" data-p="${p}">
      <div class="kr-head"><span>${s.configured ? "🟢" : "⚪"} ${p} <small>${esc(s.key || "")}</small></span>
      <a href="${LINKS[p]}" target="_blank" style="font-size:11px">get key ↗</a></div>
      ${KEYMAP[p] ? `<input type="password" id="k_${p}" placeholder="paste ${p} key (blank = keep)"/>` : `<div class="hint">local — no key. <a href="${LINKS[p]}" target="_blank">install ollama ↗</a></div>`}
      <div class="row"><select id="m_${p}"><option>models…</option></select>
      <button class="ghost test" data-test="${p}">test</button></div>
      <div class="hint" id="t_${p}"></div>
    </div>`;
  }).join("");
}
async function refreshKeysUI() {
  let s;
  try {
    s = await (await fetch(API + "/api/providers/status")).json();
  } catch {
    $("provStatus").textContent = "Backend offline — keys can't load. Start it: python main.py (or npm start). Nothing was lost; your .env is untouched.";
    return false;
  }
  if (!$("keyRows").children.length) buildKeyRows(s);
  $("provStatus").innerHTML = Object.entries(s).map(([k, v]) => `${v.configured ? "🟢" : "⚪"} ${k} <small>${esc(v.key)}</small>`).join(" • ");
  // live models per provider (parallel, best-effort)
  for (const p of PROVIDERS) {
    fetch(`${API}/api/providers/models?provider=${p}`).then(r => r.json()).then(r => {
      const sel = $("m_" + p);
      if (sel) sel.innerHTML = `<option value="">${r.live ? `⚡ ${r.models.length} live` : "curated"} — pick to use</option>` + (r.models || []).slice(0, 80).map(m => `<option>${esc(m)}</option>`).join("");
    }).catch(() => {});
  }
  return true;
}
$("keysBtn").onclick = async () => { $("keysModal").classList.remove("hidden"); buildKeyRows(); await refreshKeysUI(); };
$("closeKeys").onclick = () => $("keysModal").classList.add("hidden");
$("refreshModels").onclick = async () => {
  const ok = await refreshKeysUI();
  await loadModels($("provider").value, true);
  toast(ok ? "models refreshed live" : "backend offline — start it first");
};
$("saveKeys").onclick = async () => {
  const body = {};
  for (const p of PROVIDERS) {
    const el = $("k_" + p);
    if (el && el.value) body[KEYMAP[p]] = el.value;
  }
  if (!Object.keys(body).length) { toast("Nothing new pasted — type a key first (blank = keep)."); return; }
  try {
    const r = await (await fetch(API + "/api/keys", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json();
    if (!r.ok) throw new Error("rejected");
    for (const p of PROVIDERS) { const el = $("k_" + p); if (el) el.value = ""; }
    toast("Keys saved to backend .env — refreshing live models…");
    await refreshKeysUI(); await loadModels($("provider").value, true);
  } catch {
    toast("Save FAILED — backend offline. Start it (python main.py), then save again. Nothing was lost.");
  }
};
document.addEventListener("click", async e => {
  const b = e.target.closest("[data-test]");
  if (!b) return;
  const p = b.dataset.test;
  const modelSel = $("m_" + p);
  const model = modelSel && modelSel.value && !modelSel.value.startsWith("⚡") && !modelSel.value.startsWith("curated") && !modelSel.value.startsWith("models") ? modelSel.value : "";
  $("t_" + p).textContent = "testing…";
  try {
    const r = await (await fetch(`${API}/api/providers/test?provider=${p}${model ? "&model=" + encodeURIComponent(model) : ""}`)).json();
    $("t_" + p).textContent = r.ok ? `✅ ${r.provider}/${r.model}: ${(r.text || "").slice(0, 120)}` : `❌ ${esc((r.text || r.error || "failed").slice(0, 160))}`;
    if (r.ok && model) { $("provider").value = p; await loadModels(p); $("model").value = model; }
  } catch (err) { $("t_" + p).textContent = "❌ " + err; }
  // per-row model pick → use in top bar
  document.querySelectorAll('[id^="m_"]').forEach(sel => {
    sel.onchange = () => {
      const p2 = sel.id.replace("m_", "");
      if (sel.value && !sel.value.includes("live") && !sel.value.includes("curated")) {
        $("provider").value = p2;
        loadModels(p2).then(() => { $("model").value = sel.value; });
        toast(`using ${p2} / ${sel.value}`);
      }
    };
  });
});

/* ── chat + agent ── */
async function send(text, shot = false) {
  if (!text.trim()) return;
  // mic double-fire guard: same text twice within 2.5s = one send
  const now = Date.now();
  if (text.trim() === _lastSend.text && now - _lastSend.t < 2500) { toast("already on it…"); return; }
  _lastSend = { text: text.trim(), t: now };
  const hero = $("hero");
  if (hero) hero.style.display = "none";
  NOTE("thinking", text.slice(0, 100));
  try { if (_sendAbort) _sendAbort.abort(); } catch { }
  _sendAbort = new AbortController();
  addMsg("you", text); input.value = "";
  const bubble = addMsg("jarvis", "…");
  bubble.firstChild.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
  const agentMode = $("agentMode").checked;
  try {
    const r = await (await fetch(API + "/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" }, signal: _sendAbort.signal,
      body: JSON.stringify({ message: text, history: history.slice(-10), provider: $("provider").value, model: $("model").value || null, with_screenshot: shot, agent_mode: agentMode })
    })).json();
    let shown = r.text || r.final || JSON.stringify(r).slice(0, 2000);
    if (r.steps && r.steps.length) {
      shown += "\n\n— agent trace —\n" + r.steps.map(s => `step ${s.step}: ${((s.actions || []).map(a => a.tool).join(", ") || "answer")}`).join("\n");
    }
    bubble.firstChild.innerHTML = richBody(shown);
    bubble._fullText = shown;
    if (r.image) { const im = document.createElement("img"); im.src = r.image; bubble.appendChild(im); $("screenImg").src = r.image; }
    const meta = document.createElement("div");
    meta.className = "meta";
    const _t = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    meta.textContent = `${r.provider || "?"}${r.model ? " / " + r.model : ""}${agentMode ? " • agent" : ""} • ${_t}`;
    bubble.appendChild(meta);
    if (r.need_confirm) {
      const row = document.createElement("div");
      row.className = "actions";
      row.innerHTML = `<button data-confirm-click data-instruction="${esc(text).replace(/"/g, "&quot;")}">Confirm click</button>`;
      bubble.appendChild(row);
      toast("AI wants to click — press Confirm click, or enable autopilot.");
    }
    history.push({ role: "user", content: text }, { role: "assistant", content: shown.slice(0, 2000) });
    if (voiceOn && shown) speak(shown);
    else NOTE("idle"); // text-only reply: task is done, orb may leave
  } catch (e) {
    if (e && e.name === "AbortError") { bubble.firstChild.textContent = "Stopped."; bubble._fullText = "Stopped."; }
    else bubble.firstChild.textContent = "Backend unreachable. Run: python main.py — " + e;
  }
  withShot = false; $("plusBtn").style.borderColor = "";
}
form.onsubmit = e => { e.preventDefault(); send(input.value); };
async function runAgentGoal(goal) {
  addMsg("you", "🤖 " + goal);
  NOTE("working", goal.slice(0, 100));
  const b = addMsg("jarvis", "agent working — thinking + running tools…");
  const r = await (await fetch(API + "/api/agent/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goal, provider: $("provider").value, model: $("model").value || null }) })).json();
  b.firstChild.innerHTML = richBody(r.final + (r.steps ? "\n\n— trace —\n" + r.steps.map(s => `step ${s.step}: ${(s.actions || []).map(a => a.tool + " " + JSON.stringify(a.args || {}).slice(0, 100)).join("; ") || "answer"}\n  → ${String(s.observation || "").slice(0, 200)}`).join("\n") : ""));
  b._fullText = b.firstChild.textContent;
  if (voiceOn) speak(r.final);
  else NOTE("idle");
}
$("plusBtn").onclick = () => { withShot = !withShot; $("plusBtn").style.borderColor = withShot ? "#35e0ff" : ""; toast(withShot ? "📷 next message includes screenshot" : "screenshot off"); };

/* vision */
$("screenBtn").onclick = async () => {
  const r = await (await fetch(API + "/api/vision/screenshot")).json();
  if (r.image_b64) { $("screenImg").src = "data:image/jpeg;base64," + r.image_b64; toast("screenshot captured"); }
  else toast("screenshot failed: " + (r.error || "unknown"));
};
async function askScreen(q) {
  if (!q || !q.trim()) return;
  addMsg("you", "👁 " + q);
  const b = addMsg("jarvis", "looking at your screen…");
  NOTE("working", q.slice(0, 100));
  const r = await (await fetch(API + "/api/vision/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q, provider: $("provider").value, model: $("model").value || null }) })).json();
  b.firstChild.innerHTML = richBody(r.text);
  b._fullText = r.text;
  if (r.image) { const im = document.createElement("img"); im.src = r.image; b.appendChild(im); $("screenImg").src = r.image; }
  if (voiceOn) speak(r.text);
  else NOTE("idle");
}
$("seeBtn").onclick = () => { $("seeModal").classList.remove("hidden"); setTimeout(() => $("seeInput").focus(), 50); };
$("seeClose").onclick = () => $("seeModal").classList.add("hidden");
$("seeGo").onclick = () => { $("seeModal").classList.add("hidden"); askScreen($("seeInput").value); };
$("seeInput").addEventListener("keydown", e => { if (e.key === "Enter") $("seeGo").click(); });
$("autopilot").onchange = async e => {
  await fetch(API + "/api/control/mode", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ autopilot: e.target.checked }) });
  toast("autopilot " + (e.target.checked ? "ON — I can click freely, sir." : "OFF"));
  savePrefs();
};
$("agentMode").onchange = e => { toast(e.target.checked ? "🤖 agent ON — I’ll run commands myself" : "agent OFF"); savePrefs(); };

/* voice out — backend edge-TTS (male Ryan, your voice) first, browser male fallback.
   Raw speechSynthesis default = female + chops long text, so: pick an
   en-GB male voice, slow it down, and chain sentence chunks. */
let _maleVoice = null, _audioEl = null, _actx = null, _analyser = null;
let _voicing = false, _lastBlob = "", _lastLevel = 0;
function _ensureAudio() {
  if (!_audioEl) {
    _audioEl = new Audio();
    _audioEl.preload = "auto";
    _audioEl.onended = () => { _voicing = false; NOTE("idle"); };
    _audioEl.onpause = () => { _voicing = false; };
  }
  // one analyser for the element's lifetime → live amplitude for the orb
  if (!_actx) {
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      _actx = new AC();
      const src = _actx.createMediaElementSource(_audioEl);
      _analyser = _actx.createAnalyser();
      _analyser.fftSize = 512;
      src.connect(_analyser);
      _analyser.connect(_actx.destination);
      const buf = new Uint8Array(_analyser.fftSize);
      const tick = () => {
        if (_voicing && !_audioEl.paused) {
          _analyser.getByteTimeDomainData(buf);
          let sum = 0;
          for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
          const rms = Math.sqrt(sum / buf.length);
          if (Date.now() - _lastLevel > 90) { _lastLevel = Date.now(); NOTE("level", rms.toFixed(3)); }
        }
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    } catch { _actx = null; }
  }
  try { _actx && _actx.state === "suspended" && _actx.resume(); } catch {}
}
function pickMaleVoice() {
  try {
    const vs = speechSynthesis.getVoices() || [];
    if (!vs.length) return null;
    const pref = [
      v => /en-GB/i.test(v.lang) && /male|daniel|ryan|george|arthur|brian/i.test(v.name),
      v => /Google UK English Male/i.test(v.name),
      v => /en-GB/i.test(v.lang) && !/female|zira|samantha|karen|moira|tessa/i.test(v.name),
      v => /male|daniel|david|mark|alex|fred|ryan/i.test(v.name),
      v => /^en/i.test(v.lang),
    ];
    for (const f of pref) { const hit = vs.find(f); if (hit) return hit; }
    return vs[0];
  } catch { return null; }
}
try {
  speechSynthesis.onvoiceschanged = () => { _maleVoice = pickMaleVoice(); };
  _maleVoice = pickMaleVoice();
} catch { }
function speakBrowser(text) {
  try {
    speechSynthesis.cancel();
    if (!_maleVoice) _maleVoice = pickMaleVoice();
    // chunk on sentences so it stays continuous instead of breaking up
    const chunks = String(text).match(/[^.!?]+[.!?]+|[^.!?]+$/g) || [text];
    let i = 0;
    const next = () => {
      if (i >= chunks.length) { NOTE("idle"); return; }
      const u = new SpeechSynthesisUtterance(chunks[i++].trim().slice(0, 220));
      if (_maleVoice) u.voice = _maleVoice;
      u.lang = (_maleVoice && _maleVoice.lang) || "en-GB";
      u.rate = 0.95; u.pitch = 0.8; u.volume = 1;
      u.onend = next; u.onerror = next;
      speechSynthesis.speak(u);
    };
    next();
  } catch { }
}
async function speak(text) {
  const clean = speakable(text);
  if (!clean) return;
  NOTE("speaking", clean.slice(0, 100));
  // 1) your male edge-TTS voice from the backend
  try {
    _ensureAudio();
    try { _audioEl.pause(); } catch { }
    const r = await fetch(API + "/api/tts", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: clean })
    });
    const ct = r.headers.get("content-type") || "";
    if (r.ok && ct.includes("audio")) {
      const blob = await r.blob();
      if (_lastBlob) { try { URL.revokeObjectURL(_lastBlob); } catch {} }
      const url = URL.createObjectURL(blob);
      _lastBlob = url;
      _audioEl.src = url;
      _voicing = true;
      try { speechSynthesis.cancel(); } catch { }
      await _audioEl.play().catch(() => { _voicing = false; speakBrowser(clean); });
      return;
    }
  } catch { /* backend TTS unavailable → browser male fallback */ }
  // 2) browser fallback, forced male
  speakBrowser(clean);
}
$("speakToggle").onclick = e => { voiceOn = !voiceOn; e.target.textContent = voiceOn ? "Voice replies on" : "Voice replies off"; e.target.classList.toggle("on", voiceOn); savePrefs(); };

/* mic */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null, listening = false;
/* mic — Electron: mic→WAV→backend STT (unlimited hear, VAD stop).
   Browser: Web Speech (free, interim results). */
function _micUI(live) {
  $("micBtn").classList.toggle("live", live);
  $("micBtn").textContent = live ? "Listening — click to stop" : "Talk";
}
async function recordCommandWav() {
  // resolves Blob (16k mono WAV) / null (heard nothing or stopped early)
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
  });
  const AC = window.AudioContext || window.webkitAudioContext;
  const actx = new AC();
  const src = actx.createMediaStreamSource(stream);
  const proc = actx.createScriptProcessor(4096, 1, 1);
  const chunks = [];
  const devRate = actx.sampleRate;
  let ambientSum = 0, ambientN = 0, threshold = 0.02;
  const calEnd = performance.now() + 800;
  let speaking = false, silenceMs = 0;
  const startT = Date.now();
  const SILENCE_STOP = 1500, SAFETY = 120000;
  let stopped = false;
  window._jarvisStopRec = () => { stopped = true; };
  proc.onaudioprocess = e => {
    const d = e.inputBuffer.getChannelData(0);
    chunks.push(new Float32Array(d));
    let sum = 0;
    for (let i = 0; i < d.length; i++) sum += d[i] * d[i];
    const rms = Math.sqrt(sum / d.length);
    _micLevel = rms;
    if (performance.now() < calEnd) {
      ambientSum += rms; ambientN++;
      threshold = Math.min(0.15, Math.max(0.015, (ambientSum / Math.max(1, ambientN)) * 3));
      return;
    }
    if (rms > threshold) { speaking = true; silenceMs = 0; }
    else if (speaking) silenceMs += (d.length / e.inputBuffer.sampleRate) * 1000;
  };
  src.connect(proc); proc.connect(actx.destination);
  await new Promise(res => {
    const iv = setInterval(() => {
      if (stopped || (speaking && silenceMs >= SILENCE_STOP) || (Date.now() - startT >= SAFETY)) {
        clearInterval(iv); res();
      }
    }, 100);
  });
  try { proc.disconnect(); src.disconnect(); } catch {}
  stream.getTracks().forEach(t => { try { t.stop(); } catch {} });
  try { actx.close(); } catch {}
  window._jarvisStopRec = null;
  _micLevel = null;
  if (!speaking) return null;
  // concat + downsample to 16k mono + WAV encode
  let len = 0;
  for (const c of chunks) len += c.length;
  const raw = new Float32Array(len);
  let off = 0;
  for (const c of chunks) { raw.set(c, off); off += c.length; }
  const target = 16000;
  const ratio = devRate / target;
  const outLen = Math.floor(len / ratio);
  const out = new Int16Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const v = raw[Math.floor(i * ratio)] || 0;
    out[i] = Math.max(-32768, Math.min(32767, Math.round(v * 32768)));
  }
  const buf = new ArrayBuffer(44 + outLen * 2);
  const dv = new DataView(buf);
  const wstr = (o, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)); };
  wstr(0, "RIFF"); dv.setUint32(4, 36 + outLen * 2, true); wstr(8, "WAVE");
  wstr(12, "fmt "); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true);
  dv.setUint16(22, 1, true); dv.setUint32(24, target, true);
  dv.setUint32(28, target * 2, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true);
  wstr(36, "data"); dv.setUint32(40, outLen * 2, true);
  for (let i = 0; i < outLen; i++) dv.setInt16(44 + i * 2, out[i], true);
  return new Blob([buf], { type: "audio/wav" });
}
$("micBtn").onclick = async () => {
  if (!IS_ELECTRON) {
    if (!SR) { toast("browser STT not supported — type instead"); return; }
    if (listening) { rec.stop(); return; }
    rec = new SR(); rec.lang = "en-US"; rec.interimResults = true;
    _micUI(true); listening = true;
    NOTE("listening");
    let final = "";
    rec.onresult = e => {
      let interim = "";
      for (const r of e.results) (r.isFinal ? final += r[0].transcript : interim += r[0].transcript);
      input.value = final + interim;
    };
    rec.onend = () => { _micUI(false); listening = false; NOTE("idle"); if (final.trim()) send(final.trim()); };
    rec.onerror = (ev) => {
      listening = false; _micUI(false); NOTE("idle");
      const t = (ev && ev.error) || "";
      if (t === "not-allowed" || t === "service-not-allowed") toast("Mic blocked — allow the microphone, then try again.");
      else if (t === "audio-capture") toast("No microphone found.");
    };
    try { rec.start(); } catch { listening = false; _micUI(false); }
    return;
  }
  // ── Electron path: backend transcribes, unlimited hear time ──
  if (listening) {
    listening = false;
    try { window._jarvisStopRec && window._jarvisStopRec(); } catch {}
    return;
  }
  _micUI(true); listening = true;
  NOTE("listening");
  try {
    const blob = await recordCommandWav();
    _micUI(false); listening = false; NOTE("idle");
    if (!blob) { toast("Didn't hear anything — try again."); return; }
    toast("Transcribing…");
    const fd = new FormData();
    fd.append("f", blob, "cmd.wav");
    const r = await (await fetch(API + "/api/stt", { method: "POST", body: fd })).json();
    const txt = (r.text || "").trim();
    if (!txt || txt.startsWith("[")) { toast("Speech-to-text failed" + (txt ? ": " + txt.slice(0, 100) : ".")); return; }
    input.value = txt;
    send(txt);
  } catch (e) {
    _micUI(false); listening = false; NOTE("idle");
    toast("Mic error: " + String(e && e.message || e).slice(0, 120));
  }
};

/* ── prefs cache: provider/model/switches survive restart (server file, no keys) ── */
let _prefsT = null, _pendingModel = "";
async function loadPrefs() {
  try {
    const p = await (await fetch(API + "/api/prefs")).json();
    if (p.provider) $("provider").value = p.provider;
    if (typeof p.autopilot === "boolean") {
      $("autopilot").checked = p.autopilot;
      fetch(API + "/api/control/mode", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ autopilot: p.autopilot }) }).catch(() => {});
    }
    if (typeof p.agent_mode === "boolean") $("agentMode").checked = p.agent_mode;
    if (typeof p.voice_on === "boolean" && !p.voice_on) {
      voiceOn = false;
      $("speakToggle").textContent = "Voice replies off";
      $("speakToggle").classList.remove("on");
    }
    if (typeof p.wake_on === "boolean") {
      wakeOn = p.wake_on;
      localStorage.setItem("jarvis_wake", wakeOn ? "1" : "0");
      setWakeUI();
    }
    _pendingModel = p.model || "";
    if (p.ears_mode === "backend" || p.ears_mode === "window") {
      earsMode = p.ears_mode;
      try { $("ears").value = earsMode; } catch {}
    }
    await loadModels($("provider").value);
    if (_pendingModel) $("model").value = _pendingModel;
  } catch { /* backend down — defaults stand */ }
}
function savePrefs() {
  clearTimeout(_prefsT);
  _prefsT = setTimeout(() => {
    fetch(API + "/api/prefs", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: $("provider").value, model: $("model").value || "",
        autopilot: $("autopilot").checked, agent_mode: $("agentMode").checked,
        voice_on: voiceOn, wake_on: wakeOn, ears_mode: earsMode,
      })
    }).catch(() => {});
  }, 400);
}
/* ── wake word, always-listening, NO API KEYS ──
   Tier 1 (default, zero-install): continuous browser SpeechRecognition watching
   for "jarvis / hey jarvis / computer". Tier 2: backend sounddevice+google
   voice loop via /api/wake/* (same stack as your proven build). */
let wakeOn = localStorage.getItem("jarvis_wake") === "1", wakeRec = null, lastWakeFire = 0;
let earsMode = "window", earsLive = "off", _lastWakeToast = 0;
function setWakeUI() {
  $("wakeBtn").textContent = wakeOn ? `Wake word: listening (${earsLive === "off" ? "starting…" : earsLive})` : "Wake word: off";
  $("wakeBtn").classList.toggle("on", wakeOn);
}
function wakeToastOnce(msg) {
  if (Date.now() - _lastWakeToast > 30000) { _lastWakeToast = Date.now(); toast(msg); }
}
function startWake() {
  // backend ears work with the tab CLOSED; window ears need this tab open
  if (earsMode === "backend") {
    try { wakeRec && wakeRec.stop(); } catch {}
    earsLive = "backend"; setWakeUI();
    startBackendWake();
  } else {
    startBrowserWake(); // stops backend ears internally — one mic
  }
}
function stopWake() {
  earsLive = "off"; setWakeUI();
  try { wakeRec && wakeRec.stop(); } catch { }
  stopBackendWake();
}
setWakeUI();
function stripWakeWord(txt) {
  const m = String(txt || "").toLowerCase().match(/(hey jarvis|jarvis|computer)\s*(.*)/);
  return m ? m[2].replace(/^[,\s.!?]+/, "").trim() : "";
}
function startBrowserWake() {
  if (!SR) { toast("wake needs Chrome/Edge speech — using backend instead"); startBackendWake(); return; }
  stopBackendWake(); // one ears at a time: browser and backend share one mic/speaker
  earsLive = "window"; setWakeUI();
  try { wakeRec && wakeRec.stop(); } catch { }
  wakeRec = new SR(); wakeRec.lang = "en-US"; wakeRec.continuous = true; wakeRec.interimResults = true;
  wakeRec.onresult = e => {
    // FINAL results only + cooldown: interim echoes used to double-fire "Yes sir?"
    let finalTxt = "";
    for (const r of e.results) if (r.isFinal) finalTxt += r[0].transcript + " ";
    if (!finalTxt || !/(hey jarvis|jarvis|computer)/i.test(finalTxt)) return;
    if (Date.now() - lastWakeFire < 4000) return;
    lastWakeFire = Date.now();
    const cmd = stripWakeWord(finalTxt);
    try { wakeRec.stop(); } catch { }
    if (cmd) {
      // "jarvis how are you" in ONE breath → run it now. No "Yes sir?" first.
      input.value = cmd;
      toast("Heard: " + cmd.slice(0, 80));
      NOTE("heard", cmd);
      send(cmd);
      setTimeout(() => { if (wakeOn) startBrowserWake(); }, 3000);
    } else {
      // lone "jarvis" → invite, then mic takes the command (echoes into input)
      toast("Yes sir? listening…");
      NOTE("listening");
      speak("Yes sir?");
      setTimeout(() => $("micBtn").click(), 600);
      setTimeout(() => { if (wakeOn) startBrowserWake(); }, 12000);
    }
  };
  wakeRec.onend = () => { if (wakeOn && Date.now() - lastWakeFire > 4000) { try { wakeRec.start(); } catch { setTimeout(startBrowserWake, 1500); } } };
  wakeRec.onerror = (ev) => {
    const t = (ev && ev.error) || "";
    if (t === "not-allowed" || t === "service-not-allowed")
      wakeToastOnce("Mic blocked — allow the microphone for this site, then toggle wake off/on.");
    else if (t === "audio-capture")
      wakeToastOnce("No microphone found — plug one in, then toggle wake off/on.");
    else if (t && t !== "network" && t !== "no-speech")
      wakeToastOnce("Wake listener hiccup (" + t + ") — retrying…");
    if (wakeOn) setTimeout(() => { try { wakeRec.start(); } catch { } }, 2000);
  };
  try { wakeRec.start(); } catch { }
}
let _pollTimer = null;
const _seenCmds = new Set();
async function startBackendWake() {
  try { await fetch(API + "/api/wake/start", { method: "POST" }); toast("backend voice wake on (mic + sounddevice, no keys — same as your build)"); }
  catch { toast("backend wake unavailable"); return; }
  if (_pollTimer) return;
  let _lastWakeErr = "";
  _pollTimer = setInterval(async () => {
    try {
      const p = await (await fetch(API + "/api/wake/poll")).json();
      const st = p.state || {};
      if (st.error && st.error !== _lastWakeErr) {
        _lastWakeErr = st.error;
        toast("Backend ears problem: " + String(st.error).slice(0, 150));
      } else if (!st.error) _lastWakeErr = "";
      for (const h of (p.hits || [])) {
        if (h.kind !== "command" || !h.text) continue;  // skip "wake" dupes
        const key = h.n + "::" + h.text;
        if (_seenCmds.has(key)) continue;
        _seenCmds.add(key);
        input.value = h.text;  // prompt lands in the text space
        toast("Heard: " + h.text.slice(0, 80));
        NOTE("heard", h.text);
        send(h.text);  // real AI reply + voice
      }
    } catch { }
  }, 1500);
}
function stopBackendWake() {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  fetch(API + "/api/wake/stop", { method: "POST" }).catch(() => {});
}
$("wakeBtn").onclick = () => {
  wakeOn = !wakeOn; localStorage.setItem("jarvis_wake", wakeOn ? "1" : "0"); savePrefs();
  if (wakeOn) {
    toast(earsMode === "backend"
      ? "Backend ears ON — tab can close. Say “jarvis”."
      : "Window ears ON — keep this tab open. Say “jarvis”.");
    startWake();
  } else { stopWake(); toast("wake OFF"); }
};
$("ears").onchange = e => {
  earsMode = e.target.value === "backend" ? "backend" : "window";
  savePrefs();
  if (wakeOn) startWake();
  else setWakeUI();
};
/* boot: restore saved prefs (provider/model/switches), then resume wake if it was on */
loadPrefs().then(() => {
  if (IS_ELECTRON && earsMode === "window") {
    // Web Speech has no key in Electron — backend ears are the working path there
    try { $("ears").value = "backend"; } catch {}
    earsMode = "backend";
  }
  if (wakeOn) startWake();
});

/* palette (no native prompts — everything in-app) */
function openPalette(prefill = "") {
  $("paletteModal").classList.remove("hidden");
  $("palInput").value = prefill;
  setTimeout(() => $("palInput").focus(), 50);
}
function closePalette() { $("paletteModal").classList.add("hidden"); }
function runPaletteText(t) {
  t = (t || "").trim();
  if (!t) return;
  closePalette();
  if (t.startsWith("/agent")) runAgentGoal(t.replace("/agent", "").trim());
  else send(t);
}
document.querySelectorAll("[data-pal]").forEach(b => {
  b.onclick = () => {
    const v = b.dataset.pal;
    if (v.endsWith(" ")) { $("palInput").value = v; $("palInput").focus(); }
    else runPaletteText(v);
  };
});
$("palInput").addEventListener("keydown", e => { if (e.key === "Enter") runPaletteText($("palInput").value); });
$("palClose").onclick = closePalette;
/* hero suggestion chips */
document.querySelectorAll("[data-chip]").forEach(b => { b.onclick = () => send(b.dataset.chip); });
(function heroGreet() {
  const h = new Date().getHours();
  const day = h < 12 ? "morning" : h < 18 ? "afternoon" : "evening";
  const el = $("heroTitle");
  if (el) el.textContent = `Good ${day}, sir.`;
})();
/* palette */
document.addEventListener("keydown", e => {
  if (e.key === "Escape") { closePalette(); $("seeModal").classList.add("hidden"); $("keysModal").classList.add("hidden"); }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    $("paletteModal").classList.contains("hidden") ? openPalette() : closePalette();
  }
  if (e.key === "j" && e.altKey) $("micBtn").click();
});
