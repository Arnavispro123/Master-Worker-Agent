const { app, BrowserWindow, Tray, Menu, globalShortcut, nativeImage, ipcMain, screen } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

let win, orb, picker, tray, backend, quitting = false, orbHideTimer = null;
const BACKEND_URL = 'http://127.0.0.1:8765';
const ROOT = path.join(__dirname, '..');
const PREFS_FILE = path.join(ROOT, 'preferences.json');

/* ── prefs (shared with backend/prefs.py format) ── */
function readPrefs() {
  try { return JSON.parse(fs.readFileSync(PREFS_FILE, 'utf8')); } catch { return {}; }
}
function writePrefs(patch) {
  try {
    const p = Object.assign(readPrefs(), patch);
    fs.writeFileSync(PREFS_FILE, JSON.stringify(p, null, 2));
    return p;
  } catch { return {}; }
}

async function startBackend() {
  // main.py usually started one already — reuse it instead of a second backend
  try {
    const res = await fetch(BACKEND_URL + '/api/health');
    if (res.ok) { console.log('backend already running — using it'); return; }
  } catch {}
  // spawn python backend next to the app.
  // HUD owns mic+speakers in Electron → backend stays silent (no double voice).
  const py = process.platform === 'win32' ? 'python' : 'python3';
  const script = path.join(__dirname, '..', 'backend', 'app.py');
  const env = Object.assign({}, process.env, { JARVIS_BACKEND_VOICE: '0' });
  backend = spawn(py, [script], { cwd: path.join(__dirname, '..'), stdio: 'ignore', shell: false, env });
  backend.on('error', () => console.log('backend spawn failed — run manually: python backend/app.py'));
}

/* ── orb geometry: work area ÷ 8 zones (4 cols × 2 rows) ── */
const ORB_W = 300, ORB_H = 330, PAD = 14;
function zoneBounds(zone) {
  const area = screen.getPrimaryDisplay().workArea;
  const z = Math.max(0, Math.min(7, zone | 0));
  const col = z % 4, row = Math.floor(z / 4);
  const zw = area.width / 4, zh = area.height / 2;
  return {
    x: Math.round(area.x + col * zw + Math.max(0, (zw - ORB_W) / 2)),
    y: Math.round(area.y + row * zh + Math.max(0, (zh - ORB_H) / 2)),
  };
}
function clampOrb(x, y) {
  const area = screen.getPrimaryDisplay().workArea;
  return {
    x: Math.max(area.x, Math.min(x, area.x + area.width - ORB_W)),
    y: Math.max(area.y, Math.min(y, area.y + area.height - ORB_H)),
  };
}
function savedOrbPos() {
  const p = readPrefs();
  const area = screen.getPrimaryDisplay().workArea;
  if (typeof p.orb_fx === 'number' && typeof p.orb_fy === 'number') {
    return clampOrb(Math.round(area.x + p.orb_fx * area.width), Math.round(area.y + p.orb_fy * area.height));
  }
  return zoneBounds(typeof p.orb_zone === 'number' ? p.orb_zone : 7);
}

/* ── orb window ── */
function createOrb() {
  const pos = savedOrbPos();
  orb = new BrowserWindow({
    width: ORB_W, height: ORB_H, x: pos.x, y: pos.y,
    transparent: true, frame: false, alwaysOnTop: true, skipTaskbar: true,
    resizable: false, minimizable: false, maximizable: false,
    show: false, hasShadow: false,
    webPreferences: { preload: path.join(__dirname, 'preload.js') },
  });
  orb.loadFile(path.join(__dirname, '..', 'frontend', 'orb.html'));
  orb.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  orb.setAlwaysOnTop(true, 'screen-saver');
  screen.on('display-metrics-changed', () => { if (orb && !orb.isDestroyed()) { const q = savedOrbPos(); orb.setBounds({ x: q.x, y: q.y, width: ORB_W, height: ORB_H }); } });
}
/* first-run placement picker: full-screen 8-zone map */
function createPicker() {
  const area = screen.getPrimaryDisplay().workArea;
  picker = new BrowserWindow({
    width: area.width, height: area.height, x: area.x, y: area.y,
    transparent: true, frame: false, alwaysOnTop: true, skipTaskbar: true,
    resizable: false, webPreferences: { preload: path.join(__dirname, 'preload.js') },
  });
  picker.loadFile(path.join(__dirname, '..', 'frontend', 'place.html'));
  picker.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
}
function showOrb(activity, text) {
  if (!orb || orb.isDestroyed()) return;
  try { orb.showInactive(); } catch {}
  try { orb.webContents.send('orb-activity', { activity, text: String(text || '').slice(0, 160), t: Date.now() }); } catch {}
}
function hideOrb() {
  orbBusy = false;
  clearTimeout(orbHideTimer);
  try { orb && !orb.isDestroyed() && orb.hide(); } catch {}
}

/* HUD → orb bridge. Busy-state machine, not a dumb timer:
   speaking/listening/working/thinking = STAY until explicit idle.
   heard = show 9s (a command/thinking note always follows). */
let orbBusy = false;
function pokeOrbHide(ms) {
  clearTimeout(orbHideTimer);
  orbHideTimer = setTimeout(() => { orbBusy = false; try { orb && !orb.isDestroyed() && orb.hide(); } catch {} }, ms);
}
ipcMain.on('hud-activity', (_e, d) => {
  const kind = (d && d.kind) || 'idle';
  if (kind === 'level') {
    // voice amplitude @~12Hz: forward only + 30s watchdog in case idle is lost
    try { orb && !orb.isDestroyed() && orb.webContents.send('orb-activity', { activity: 'level', level: d.level, t: Date.now() }); } catch {}
    if (orbBusy) pokeOrbHide(30000);
    return;
  }
  if (kind === 'speaking' || kind === 'listening' || kind === 'working' || kind === 'thinking') {
    orbBusy = true;
    clearTimeout(orbHideTimer);
    showOrb(kind === 'thinking' ? 'working' : kind, d.text);
    return;
  }
  if (kind === 'heard') {
    showOrb('heard', d.text);
    if (!orbBusy) pokeOrbHide(9000);
    return;
  }
  orbBusy = false;
  pokeOrbHide(2500);
});
ipcMain.on('orb-click', () => {
  if (win) { win.show(); try { win.focus(); } catch {} }
});
/* orb drag → move + persist fractional position */
ipcMain.on('orb-drag', (_e, d) => {
  try {
    if (!orb || orb.isDestroyed()) return;
    const [x, y] = orb.getPosition();
    const q = clampOrb(x + (d.dx || 0), y + (d.dy || 0));
    orb.setPosition(q.x, q.y);
  } catch {}
});
ipcMain.on('orb-drag-end', () => {
  try {
    if (!orb || orb.isDestroyed()) return;
    const area = screen.getPrimaryDisplay().workArea;
    const [x, y] = orb.getPosition();
    writePrefs({ orb_fx: (x - area.x) / area.width, orb_fy: (y - area.y) / area.height });
  } catch {}
});
/* placement choice from picker */
ipcMain.on('orb-placed', (_e, d) => {
  const zone = Math.max(0, Math.min(7, (d && d.zone) | 0));
  try {
    const prefs = readPrefs();
    delete prefs.orb_fx; delete prefs.orb_fy;
    prefs.orb_zone = zone; prefs.orb_placed = true;
    fs.writeFileSync(PREFS_FILE, JSON.stringify(prefs, null, 2));
  } catch {}
  try { picker && picker.close(); } catch {}
  picker = null;
  if (!orb || orb.isDestroyed()) createOrb();
  const q = zoneBounds(zone);
  try { orb.setBounds({ x: q.x, y: q.y, width: ORB_W, height: ORB_H }); } catch {}
  showOrb('idle', 'I’ll rest here, sir.');
});
ipcMain.handle('get-work-area', () => {
  const a = screen.getPrimaryDisplay().workArea;
  return { x: a.x, y: a.y, width: a.width, height: a.height };
});

/* ── main window ── */
function createWindow() {
  const area = screen.getPrimaryDisplay().workArea; // excludes taskbar
  const w = Math.min(1180, Math.max(900, area.width - 80));
  const h = Math.min(800, Math.max(600, area.height - 80));
  win = new BrowserWindow({
    width: w, height: h, backgroundColor: '#04070d',
    minWidth: 900, minHeight: 600, fullscreen: false, fullscreenable: true,
    webPreferences: { preload: path.join(__dirname, 'preload.js') },
    autoHideMenuBar: true,
  });
  win.loadFile(path.join(__dirname, '..', 'frontend', 'index.html'));
  win.setMenuBarVisibility(false);
  win.maximize(); // snap to work area so the taskbar is never covered
  // close → hide to tray (background), real quit comes from the tray menu
  win.on('close', (e) => {
    if (!quitting) { e.preventDefault(); win.hide(); }
  });
  const tryLoad = async (n = 0) => {
    try {
      const res = await fetch(BACKEND_URL + '/api/health');
      if (res.ok) return win.loadURL(BACKEND_URL);
    } catch {}
    if (n < 30) setTimeout(() => tryLoad(n + 1), 500);
    else win.loadFile(path.join(__dirname, '..', 'frontend', 'index.html'));
  };
  tryLoad();
}

/* ── tray: run in background ── */
function createTray() {
  let icon;
  try {
    icon = nativeImage.createFromPath(path.join(__dirname, 'tray.png'));
    if (icon.isEmpty()) icon = undefined;
  } catch { icon = undefined; }
  tray = new Tray(icon || nativeImage.createEmpty());
  tray.setToolTip('JARVIS — running in background');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Show Jarvis', click: () => { win && win.show(); } },
    { label: 'Show orb', click: () => showOrb('idle', 'at your service, sir.') },
    { label: 'Move orb…', click: () => { hideOrb(); if (!picker || picker.isDestroyed()) createPicker(); else picker.show(); } },
    { type: 'separator' },
    { label: 'Quit Jarvis', click: () => { quitting = true; app.quit(); } },
  ]));
  tray.on('click', () => { if (win) { win.isVisible() ? win.hide() : win.show(); } });
}

// one Jarvis only: a second launch focuses the running one (no twin backends/orbs)
if (!app.requestSingleInstanceLock()) app.quit();
app.on('second-instance', () => {
  if (win) { win.isVisible() ? win.focus() : win.show(); }
});

app.whenReady().then(() => {
  // mic permission for the HUD voice recorder (Electron denies media by default)
  try {
    const { session } = require('electron');
    session.defaultSession.setPermissionRequestHandler((wc, permission, cb) => {
      cb(permission === 'media' || permission === 'audio-capture');
    });
  } catch {}
  startBackend();
  const prefs = readPrefs();
  if (!prefs.orb_placed && typeof prefs.orb_zone !== 'number') {
    createPicker(); // first run: ask where the orb should rest
  }
  createOrb();
  createWindow();
  createTray();
  try {
    globalShortcut.register('Alt+J', () => win && (win.show(), win.focus()));
  } catch {}
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); else win && win.show(); });
});
app.on('window-all-closed', () => { /* tray keeps us alive */ if (process.platform === 'darwin') app.quit(); });
app.on('before-quit', () => { quitting = true; });
app.on('quit', () => { try { backend && backend.kill(); } catch {} });
