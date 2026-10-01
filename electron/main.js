const { app, BrowserWindow, Tray, Menu, globalShortcut, nativeImage, ipcMain, screen } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

let win, orb, tray, backend, quitting = false, orbHideTimer = null;
const BACKEND_URL = 'http://127.0.0.1:8765';

function startBackend() {
  // spawn python backend next to the app
  const py = process.platform === 'win32' ? 'python' : 'python3';
  const script = path.join(__dirname, '..', 'backend', 'app.py');
  backend = spawn(py, [script], { cwd: path.join(__dirname, '..'), stdio: 'ignore', shell: false });
  backend.on('error', () => console.log('backend spawn failed — run manually: python backend/app.py'));
}

/* ── orb: circular semi-transparent overlay, bottom-right ── */
function orbPosition() {
  const area = screen.getPrimaryDisplay().workArea; // respects taskbar
  const W = 300, H = 330;
  return { x: Math.max(0, area.x + area.width - W - 14), y: Math.max(0, area.y + area.height - H - 14), W, H };
}
function createOrb() {
  const { x, y, W, H } = orbPosition();
  orb = new BrowserWindow({
    width: W, height: H, x, y,
    transparent: true, frame: false, alwaysOnTop: true, skipTaskbar: true,
    resizable: false, minimizable: false, maximizable: false,
    focusable: false, show: false, hasShadow: false,
    webPreferences: { preload: path.join(__dirname, 'preload.js') },
  });
  orb.loadFile(path.join(__dirname, '..', 'frontend', 'orb.html'));
  orb.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  orb.setAlwaysOnTop(true, 'screen-saver');
  // click orb → bring main window forward
  orb.webContents.on('ipc-message', () => {});
  screen.on('display-metrics-changed', () => { if (orb) { const p = orbPosition(); orb.setBounds({ x: p.x, y: p.y, width: p.W, height: p.H }); } });
}
function showOrb(activity, text) {
  if (!orb) return;
  orb.showInactive();
  try { orb.webContents.send('orb-activity', { activity, text: String(text || '').slice(0, 160), t: Date.now() }); } catch {}
  clearTimeout(orbHideTimer);
  if (activity !== 'listening') {
    orbHideTimer = setTimeout(() => { try { orb.hide(); } catch {} }, 9000);
  }
}
function hideOrb() {
  clearTimeout(orbHideTimer);
  try { orb && orb.hide(); } catch {}
}

/* HUD → orb bridge: renderer calls window.jarvisAPI.notify(kind, text) */
ipcMain.on('hud-activity', (_e, d) => {
  const kind = (d && d.kind) || 'idle';
  if (kind === 'speaking') showOrb('speaking', d.text);
  else if (kind === 'listening') showOrb('listening', d.text || 'listening…');
  else if (kind === 'working' || kind === 'thinking') showOrb('working', d.text);
  else if (kind === 'heard') showOrb('heard', d.text);
  else hideOrb();
});
ipcMain.on('orb-click', () => {
  if (win) { win.show(); try { win.focus(); } catch {} }
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
    { type: 'separator' },
    { label: 'Quit Jarvis', click: () => { quitting = true; app.quit(); } },
  ]));
  tray.on('click', () => { if (win) { win.isVisible() ? win.hide() : win.show(); } });
}

app.whenReady().then(() => {
  startBackend();
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
