const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('ankita', {
  redact: text => ipcRenderer.invoke('engine:invoke', 'redact', { text }),
  invoke: (action, payload) => ipcRenderer.invoke('engine:invoke', action, payload),
  onEvent: callback => {
    const listener = (_event, value) => callback(value);
    ipcRenderer.on('engine:event', listener);
    return () => ipcRenderer.removeListener('engine:event', listener);
  },
  onMenuCommand: callback => {
    const listener = (_event, value) => callback(value);
    ipcRenderer.on('menu:command', listener);
    return () => ipcRenderer.removeListener('menu:command', listener);
  },
  onUpdateEvent: callback => {
    const listener = (_event, value) => callback(value);
    ipcRenderer.on('update:event', listener);
    return () => ipcRenderer.removeListener('update:event', listener);
  },
  updateAction: action => ipcRenderer.invoke('update:action', action),
  appAction: action => ipcRenderer.invoke('app:action', action),
  windowAction: action => ipcRenderer.invoke('window:action', action),
  islandAction: (action, options) => ipcRenderer.invoke('island:action', action, options),
  onCursor: callback => {
    const listener = (_event, value) => callback(value);
    ipcRenderer.on('island:cursor', listener);
    return () => ipcRenderer.removeListener('island:cursor', listener);
  },
  openExternal: url => ipcRenderer.invoke('open-external', url),
});
