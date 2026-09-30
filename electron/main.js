const { app, BrowserWindow, Tray, Menu, globalShortcut, Menu: _m } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

let win, backend;
const BACKEND_URL = 'http://127.0.0.1:8765';

function startBackend() {
  // spawn python backend next to the app
  const py = process.platform === 'win32' ? 'python' : 'python3';
  const script = path.join(__dirname, '..', 'backend', 'app.py');
  backend = spawn(py, [script], { cwd: path.join(__dirname, '..'), stdio: 'ignore', shell: false });
  backend.on('error', () => console.log('backend spawn failed — run manually: python backend/app.py'));
}

function createWindow() {
  const { screen } = require('electron');
  const area = screen.getPrimaryDisplay().workArea; // excludes taskbar
  const w = Math.min(1180, Math.max(900, area.width - 80));
  const h = Math.min(800, Math.max(600, area.height - 80));
  win = new BrowserWindow({
    width: w, height: h, backgroundColor: '#04070d',
    minWidth: 900, minHeight: 600, fullscreen: false, fullscreenable: true,
    webPreferences: { preload: path.join(__dirname, 'preload.js') },
    autoHideMenuBar: true,
  });
  const tryLoad = async (n = 0) => {
    try {
      const res = await fetch(BACKEND_URL + '/api/health');
      if (res.ok) return win.loadURL(BACKEND_URL);
    } catch {}
    if (n < 30) setTimeout(() => tryLoad(n + 1), 500);
    else win.loadFile(path.join(__dirname, '..', 'frontend', 'index.html'));
  };
  win.loadFile(path.join(__dirname, '..', 'frontend', 'index.html'));
  win.setMenuBarVisibility(false);
  win.maximize(); // snap to work area so the taskbar is never covered
  tryLoad();
}

app.whenReady().then(() => {
  startBackend();
  createWindow();
  try {
    globalShortcut.register('Alt+J', () => win && (win.show(), win.focus()));
  } catch {}
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('quit', () => { try { backend && backend.kill(); } catch {} });
