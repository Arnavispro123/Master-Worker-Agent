const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('jarvisAPI', {
  base: 'http://127.0.0.1:8765',
  isElectron: true,
  // HUD → orb bridge (no-op safe in plain browsers)
  notify: (kind, text) => {
    try { ipcRenderer.send('hud-activity', { kind, text: String(text || '').slice(0, 140) }); } catch {}
  },
  orbClick: () => {
    try { ipcRenderer.send('orb-click'); } catch {}
  },
  onOrb: (fn) => {
    try { ipcRenderer.on('orb-activity', (_e, d) => { try { fn(d); } catch {} }); } catch {}
  },
});
