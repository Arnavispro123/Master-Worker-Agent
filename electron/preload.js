const { contextBridge } = require('electron');
contextBridge.exposeInMainWorld('jarvisAPI', { base: 'http://127.0.0.1:8765', isElectron: true });
