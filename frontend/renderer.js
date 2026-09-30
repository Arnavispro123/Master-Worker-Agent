/* JARVIS renderer — chat + agent + live models + offline wake-word + voice */
const API = (window.jarvisAPI && window.jarvisAPI.base) || "http://127.0.0.1:8765";
const $ = id => document.getElementById(id);
const chat = $("chat"), form = $("form"), input = $("input");
let history = [], voiceOn = true, withShot = false;
let _sendAbort = null, _lastSend = { text: "", t: 0 };
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
    const y = 32 + Math.sin(x * 0.15 + Date.now() / 200) * 20 * level * (0.5 + Math.random());
    x ? wv.lineTo(x, y) : wv.moveTo(x, y);
  }
  wv.stroke(); requestAnimationFrame(() => wave(level));
}
wave();

function toast(m) { const e = $("toast"); e.textContent = m; e.style.display = "block"; setTimeout(() => e.style.display = "none", 3000); }
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
    $("status").textContent = `online • ${new Date().toLocaleTimeString()} • autopilot ${r.autopilot ? "ON" : "OFF"}`;
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
  } catch { sel.innerHTML = `<option value="">auto model</option>`; }
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
  const s = await (await fetch(API + "/api/providers/status")).json();
  if (!$("keyRows").children.length) buildKeyRows(s);
  $("provStatus").innerHTML = Object.entries(s).map(([k, v]) => `${v.configured ? "🟢" : "⚪"} ${k} <small>${esc(v.key)}</small>`).join(" • ");
  // live models per provider (parallel, best-effort)
  for (const p of PROVIDERS) {
    fetch(`${API}/api/providers/models?provider=${p}`).then(r => r.json()).then(r => {
      const sel = $("m_" + p);
      if (sel) sel.innerHTML = `<option value="">${r.live ? `⚡ ${r.models.length} live` : "curated"} — pick to use</option>` + (r.models || []).slice(0, 80).map(m => `<option>${esc(m)}</option>`).join("");
    }).catch(() => {});
  }
}
$("keysBtn").onclick = async () => { $("keysModal").classList.remove("hidden"); buildKeyRows(); await refreshKeysUI(); };
$("closeKeys").onclick = () => $("keysModal").classList.add("hidden");
$("refreshModels").onclick = async () => { await refreshKeysUI(); await loadModels($("provider").value, true); toast("models refreshed live"); };
$("saveKeys").onclick = async () => {
  const body = {};
  for (const p of PROVIDERS) {
    const el = $("k_" + p);
    if (el && el.value) body[KEYMAP[p]] = el.value;
  }
  await fetch(API + "/api/keys", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  toast("keys saved — refreshing live models…");
  await refreshKeysUI(); await loadModels($("provider").value, true);
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
  try { if (_sendAbort) _sendAbort.abort(); } catch { }
  _sendAbort = new AbortController();
  addMsg("you", text); input.value = "";
  const bubble = addMsg("jarvis", "…");
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
    bubble.firstChild.textContent = shown;
    bubble._fullText = shown;
    if (r.image) { const im = document.createElement("img"); im.src = r.image; bubble.appendChild(im); $("screenImg").src = r.image; }
    const meta = document.createElement("div");
    meta.className = "meta"; meta.textContent = `${r.provider || "?"}${r.model ? " / " + r.model : ""}${agentMode ? " • agent" : ""}`;
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
  } catch (e) {
    if (e && e.name === "AbortError") { bubble.firstChild.textContent = "Stopped."; bubble._fullText = "Stopped."; }
    else bubble.firstChild.textContent = "Backend unreachable. Run: python main.py — " + e;
  }
  withShot = false; $("plusBtn").style.borderColor = "";
}
form.onsubmit = e => { e.preventDefault(); send(input.value); };
async function runAgentGoal(goal) {
  addMsg("you", "🤖 " + goal);
  const b = addMsg("jarvis", "agent working — thinking + running tools…");
  const r = await (await fetch(API + "/api/agent/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goal, provider: $("provider").value, model: $("model").value || null }) })).json();
  b.firstChild.textContent = r.final + (r.steps ? "\n\n— trace —\n" + r.steps.map(s => `step ${s.step}: ${(s.actions || []).map(a => a.tool + " " + JSON.stringify(a.args || {}).slice(0, 100)).join("; ") || "answer"}\n  → ${String(s.observation || "").slice(0, 200)}`).join("\n") : "");
  b._fullText = b.firstChild.textContent;
  if (voiceOn) speak(r.final);
}
$("plusBtn").onclick = () => { withShot = !withShot; $("plusBtn").style.borderColor = withShot ? "#35e0ff" : ""; toast(withShot ? "📷 next message includes screenshot" : "screenshot off"); };

/* vision */
$("screenBtn").onclick = async () => {
  const r = await (await fetch(API + "/api/vision/screenshot")).json();
  if (r.image_b64) { $("screenImg").src = "data:image/jpeg;base64," + r.image_b64; toast("screenshot captured"); }
  else toast("screenshot failed: " + (r.error || "unknown"));
};
$("seeBtn").onclick = async () => {
  const q = prompt("Ask about your screen:", "What do you see? Summarize windows and suggest next action.");
  if (!q) return;
  addMsg("you", "👁 " + q);
  const b = addMsg("jarvis", "looking at your screen…");
  const r = await (await fetch(API + "/api/vision/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q, provider: $("provider").value, model: $("model").value || null }) })).json();
  b.firstChild.textContent = r.text;
  if (r.image) { const im = document.createElement("img"); im.src = r.image; b.appendChild(im); $("screenImg").src = r.image; }
  if (voiceOn) speak(r.text);
};
$("autopilot").onchange = async e => {
  await fetch(API + "/api/control/mode", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ autopilot: e.target.checked }) });
  toast("autopilot " + (e.target.checked ? "ON — I can click freely, sir." : "OFF"));
  savePrefs();
};
$("agentMode").onchange = e => { toast(e.target.checked ? "🤖 agent ON — I’ll run commands myself" : "agent OFF"); savePrefs(); };

/* voice out — backend edge-TTS (male Ryan, your voice) first, browser male fallback.
   Raw speechSynthesis default = female + chops long text, so: pick an
   en-GB male voice, slow it down, and chain sentence chunks. */
let _maleVoice = null, _audioEl = null;
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
      if (i >= chunks.length) return;
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
  // 1) your male edge-TTS voice from the backend
  try {
    if (_audioEl) { try { _audioEl.pause(); } catch { } }
    const r = await fetch(API + "/api/tts", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: clean })
    });
    const ct = r.headers.get("content-type") || "";
    if (r.ok && ct.includes("audio")) {
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      _audioEl = new Audio(url);
      try { speechSynthesis.cancel(); } catch { }
      await _audioEl.play().catch(() => speakBrowser(clean));
      return;
    }
  } catch { /* backend TTS unavailable → browser male fallback */ }
  // 2) browser fallback, forced male
  speakBrowser(clean);
}
$("speakToggle").onclick = e => { voiceOn = !voiceOn; e.target.textContent = voiceOn ? "🔊 voice replies ON" : "🔇 voice replies OFF"; e.target.classList.toggle("on", voiceOn); savePrefs(); };

/* mic */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null, listening = false;
$("micBtn").onclick = () => {
  if (!SR) { toast("browser STT not supported — type instead"); return; }
  if (listening) { rec.stop(); return; }
  rec = new SR(); rec.lang = "en-US"; rec.interimResults = true;
  $("micBtn").classList.add("live"); $("micBtn").textContent = "🔴 listening… click to stop"; listening = true;
  let final = "";
  rec.onresult = e => {
    let interim = "";
    for (const r of e.results) (r.isFinal ? final += r[0].transcript : interim += r[0].transcript);
    input.value = final + interim;
  };
  rec.onend = () => { $("micBtn").classList.remove("live"); $("micBtn").textContent = "🎙 hold / click to talk"; listening = false; if (final.trim()) send(final.trim()); };
  rec.onerror = () => { listening = false; $("micBtn").classList.remove("live"); };
  rec.start();
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
      $("speakToggle").textContent = "🔇 voice replies OFF";
      $("speakToggle").classList.remove("on");
    }
    if (typeof p.wake_on === "boolean") {
      wakeOn = p.wake_on;
      localStorage.setItem("jarvis_wake", wakeOn ? "1" : "0");
      setWakeUI();
    }
    _pendingModel = p.model || "";
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
        voice_on: voiceOn, wake_on: wakeOn,
      })
    }).catch(() => {});
  }, 400);
}
/* ── wake word, always-listening, NO API KEYS ──
   Tier 1 (default, zero-install): continuous browser SpeechRecognition watching
   for "jarvis / hey jarvis / computer". Tier 2: backend sounddevice+google
   voice loop via /api/wake/* (same stack as your proven build). */
let wakeOn = localStorage.getItem("jarvis_wake") === "1", wakeRec = null, lastWakeFire = 0;
function setWakeUI() { $("wakeBtn").textContent = wakeOn ? "👂 wake: LISTENING (say “jarvis”)" : "👂 wake: OFF"; $("wakeBtn").classList.toggle("on", wakeOn); }
setWakeUI();
function stripWakeWord(txt) {
  const m = String(txt || "").toLowerCase().match(/(hey jarvis|jarvis|computer)\s*(.*)/);
  return m ? m[2].replace(/^[,\s.!?]+/, "").trim() : "";
}
function startBrowserWake() {
  if (!SR) { toast("wake needs Chrome/Edge speech — using backend instead"); startBackendWake(); return; }
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
      toast("👂 heard: " + cmd.slice(0, 80));
      send(cmd);
      setTimeout(() => { if (wakeOn) startBrowserWake(); }, 3000);
    } else {
      // lone "jarvis" → invite, then mic takes the command (echoes into input)
      toast("👂 yes sir? listening…");
      speak("Yes sir?");
      setTimeout(() => $("micBtn").click(), 600);
      setTimeout(() => { if (wakeOn) startBrowserWake(); }, 12000);
    }
  };
  wakeRec.onend = () => { if (wakeOn && Date.now() - lastWakeFire > 4000) { try { wakeRec.start(); } catch { setTimeout(startBrowserWake, 1500); } } };
  wakeRec.onerror = () => { if (wakeOn) setTimeout(() => { try { wakeRec.start(); } catch { } }, 2000); };
  try { wakeRec.start(); } catch { }
}
let _pollTimer = null;
const _seenCmds = new Set();
async function startBackendWake() {
  try { await fetch(API + "/api/wake/start", { method: "POST" }); toast("backend voice wake on (mic + sounddevice, no keys — same as your build)"); }
  catch { toast("backend wake unavailable"); return; }
  if (_pollTimer) return;
  _pollTimer = setInterval(async () => {
    try {
      const p = await (await fetch(API + "/api/wake/poll")).json();
      for (const h of (p.hits || [])) {
        if (h.kind !== "command" || !h.text) continue;  // skip "wake" dupes
        const key = h.n + "::" + h.text;
        if (_seenCmds.has(key)) continue;
        _seenCmds.add(key);
        input.value = h.text;  // prompt lands in the text space
        toast("👂 heard: " + h.text.slice(0, 80));
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
  wakeOn = !wakeOn; localStorage.setItem("jarvis_wake", wakeOn ? "1" : "0"); setWakeUI(); savePrefs();
  if (wakeOn) { toast("wake ON — say “jarvis”. No keys, all local."); startBrowserWake(); }
  else { try { wakeRec && wakeRec.stop(); } catch { } stopBackendWake(); toast("wake OFF"); }
};
/* boot: restore saved prefs (provider/model/switches), then resume wake if it was on */
loadPrefs().then(() => { if (wakeOn) startBrowserWake(); });

/* palette */
document.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    const c = prompt("chat | /agent <goal> (I run it) | /research <topic> (I read the web) | /see | /screenshot | /click <what> | /search <q>", "/research ");
    if (c) (c.startsWith("/agent") ? runAgentGoal(c.replace("/agent", "").trim()) : send(c));
  }
  if (e.key === "j" && e.altKey) $("micBtn").click();
});
setTimeout(() => {
  const h = new Date().getHours();
  const day = h < 12 ? "morning" : h < 18 ? "afternoon" : "evening";
  addMsg("jarvis", `Good ${day}, sir. Agent mode can run shell/files/web by itself — toggle “agent” or type “do: …”. Wake word 👂 works with zero keys. Press 🔑 to paste keys — models load live.`, "jarvis • ready");
}, 600);
