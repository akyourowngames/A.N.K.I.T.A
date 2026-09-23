import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { app, BrowserWindow, ipcMain, shell, Menu, screen } from 'electron';
import { DesktopEngine } from './engine.mjs';
import { windowChrome } from './window-chrome.mjs';
import { loadWindowState, saveWindowState, visibleBounds } from './window-state.mjs';
import { menuTemplate } from './menu.mjs';
import { setupUpdater } from './updater.mjs';
import { CONFIG_DIR } from '../../src/config.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const APP_NAME = 'Ankita';
const APP_ID = 'com.ankita.desktop';
const isDev = Boolean(process.env.ANKITA_DESKTOP_DEV_URL);
const isPortable = Boolean(process.env.PORTABLE_EXECUTABLE_DIR);
const windowStateFile = () => path.join(app.getPath('userData'), 'window-state.json');

let window = null;
let engine = null;
let updater = null;
let saveTimer = null;
let crashes = 0;

app.setName(APP_NAME);
app.setAppUserModelId(APP_ID);
app.setAboutPanelOptions({
  applicationName: APP_NAME,
  applicationVersion: app.getVersion(),
  copyright: 'Copyright © 2026 Ankita',
});

function persistWindowState() {
  if (window && !window.isDestroyed()) saveWindowState(windowStateFile(), window);
}

function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(persistWindowState, 400);
}

function dispatch(name) {
  const target = BrowserWindow.getFocusedWindow() || window;
  if (target && !target.isDestroyed()) target.webContents.send('menu:command', name);
}

function checkForUpdates() {
  // Marked manual so the renderer reports "already up to date" and errors that
  // a silent background check would keep quiet. Sent before the usability check
  // so the "not supported in this build" message is shown too.
  window?.webContents.send('update:event', { type: 'checking', manual: true });
  if (!updater?.usable) {
    window?.webContents.send('update:event', { type: 'unsupported' });
    return;
  }
  void updater.check();
}

function installMenu() {
  const template = menuTemplate({
    isMac: process.platform === 'darwin',
    isDev,
    send: dispatch,
    openConfigFolder: () => void shell.openPath(CONFIG_DIR),
    openDataFolder: () => void shell.openPath(app.getPath('userData')),
    checkForUpdates,
    about: APP_NAME,
  });
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function openExternal(value) {
  try {
    const url = new URL(String(value));
    if (url.protocol !== 'https:' && url.protocol !== 'http:') return;
    void shell.openExternal(url.toString());
  } catch {
    // Ignore anything that is not a well-formed web URL.
  }
}

function createWindow() {
  const chrome = windowChrome();
  const saved = visibleBounds(loadWindowState(windowStateFile()), screen.getAllDisplays());
  window = new BrowserWindow({
    width: saved.width,
    height: saved.height,
    x: saved.x,
    y: saved.y,
    minWidth: 840,
    minHeight: 560,
    title: APP_NAME,
    backgroundColor: '#13161a',
    show: false,
    ...(chrome.frame === false ? { frame: false } : {}),
    ...(chrome.titleBarStyle ? { titleBarStyle: chrome.titleBarStyle } : {}),
    webPreferences: {
      preload: path.join(here, 'preload.cjs'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
      spellcheck: false,
    },
  });
  if (saved.maximized) window.maximize();

  window.once('ready-to-show', () => window?.show());
  window.webContents.setWindowOpenHandler(({ url }) => {
    openExternal(url);
    return { action: 'deny' };
  });
  window.webContents.on('will-navigate', event => event.preventDefault());
  window.webContents.on('render-process-gone', () => {
    // A renderer crash should not end the session; recover a couple of times.
    if (crashes < 3) {
      crashes++;
      window?.reload();
    }
  });
  window.on('resize', scheduleSave);
  window.on('move', scheduleSave);
  window.on('close', persistWindowState);
  window.on('closed', () => { window = null; });

  if (isDev) {
    void window.loadURL(process.env.ANKITA_DESKTOP_DEV_URL);
  } else {
    void window.loadFile(path.join(here, '../renderer/dist/index.html'));
  }

  engine = new DesktopEngine({
    emit: event => {
      if (window && !window.isDestroyed()) window.webContents.send('engine:event', event);
    },
  });

  updater = setupUpdater({
    isPackaged: app.isPackaged,
    isDev,
    isPortable,
    emit: event => {
      if (window && !window.isDestroyed()) window.webContents.send('update:event', event);
    },
  });
  // Quiet startup check, after the app has settled, so it never competes with
  // provider sign-in or a first message.
  setTimeout(() => { if (updater?.usable) void updater.check(); }, 6000);
}

function requiredEngine() {
  if (!engine) throw new Error('Desktop engine is not ready');
  return engine;
}

ipcMain.handle('engine:invoke', async (_event, action, payload) => {
  const current = requiredEngine();
  if (action === 'initialize') {
    await current.init();
    return {
      teammates: current.listTeammates(),
      models: current.listModels(),
      settings: current.getSettingsSummary(),
      preferences: current.getDesktopPreferences(),
      version: app.getVersion(),
      chrome: windowChrome().controls,
    };
  }
  await current.init();
  switch (action) {
    case 'listTeammates': return current.listTeammates();
    case 'listProjects': return current.listProjects();
    case 'createProject': return current.createProject(payload);
    case 'updateProject': return current.updateProject(payload.id, payload.patch);
    case 'assignProject': return current.assignProject(payload.id, payload.projectId);
    case 'addProjectTodo': return current.addProjectTodo(payload.id, payload.text);
    case 'addProjectRecord': return current.addProjectRecord(payload.id, payload.kind, payload.text);
    case 'completeProjectTodo': return current.completeProjectTodo(payload.id, payload.ref);
    case 'workspaceSnapshot': return current.workspaceSnapshot(payload.id);
    case 'workspaceDiff': return current.workspaceDiff(payload.id, payload.path);
    case 'stopWorkspaceJob': return current.stopWorkspaceJob(payload.id, payload.jobId);
    case 'showWorkspaceFile': {
      const snapshot = await current.workspaceSnapshot(payload.id);
      const absolute = path.resolve(snapshot.root, payload.path);
      const artifact = snapshot.artifacts.find(item => item.path === absolute);
      const changed = snapshot.files.find(item => path.resolve(snapshot.root, item.path) === absolute);
      if (!artifact && !changed) throw new Error('File is no longer available in this workspace');
      shell.showItemInFolder(absolute);
      return true;
    }
    case 'createTeammate': return current.createTeammate(payload);
    case 'updateTeammate': return current.updateTeammate(payload.id, payload.patch);
    case 'deleteTeammate': return current.deleteTeammate(payload.id);
    case 'loadThread': return current.loadThread(payload.id);
    case 'clearThread': return current.clearThread(payload.id);
    case 'send': return current.send(payload.id, payload.text);
    case 'cancel': return current.cancel(payload.id);
    case 'respondApproval': return current.respondApproval(payload.requestId, payload.answer);
    case 'listModels': return current.listModels();
    case 'setModel': return current.setModel(payload.id, payload.modelId);
    case 'settingsSummary': return current.getSettingsSummary();
    case 'getDesktopPreferences': return current.getDesktopPreferences();
    case 'saveDesktopSettings': return current.saveDesktopSettings(payload);
    case 'testCustomProvider': return current.testCustomProvider(payload);
    case 'pluginsOverview': return current.plugins.overview();
    case 'pluginsCatalog': return current.plugins.catalog(payload);
    case 'pluginsConnect': return current.plugins.connect(payload);
    case 'pluginsDisconnectAccount': return current.plugins.disconnectAccount(payload);
    case 'pluginsDisconnectService': return current.plugins.disconnectService(payload);
    case 'pluginsRefresh': return current.refreshPlugins();
    case 'appInfo': return { version: app.getVersion() };
    default: throw new Error('Unknown desktop action');
  }
});

ipcMain.handle('window:action', (_event, action) => {
  if (!window) return false;
  if (action === 'minimize') window.minimize();
  else if (action === 'maximize') window.isMaximized() ? window.unmaximize() : window.maximize();
  else if (action === 'close') window.close();
  else return false;
  return true;
});

ipcMain.handle('open-external', (_event, value) => openExternal(value));

ipcMain.handle('app:action', (_event, action) => {
  if (action === 'open-config-folder') return shell.openPath(CONFIG_DIR);
  if (action === 'open-data-folder') return shell.openPath(app.getPath('userData'));
  return null;
});

ipcMain.handle('update:action', (_event, action) => {
  if (!updater) return false;
  if (action === 'check') {
    checkForUpdates();
    return true;
  }
  if (action === 'install') return updater.install();
  return false;
});

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (!window) return;
    if (window.isMinimized()) window.restore();
    window.show();
    window.focus();
  });

  app.whenReady().then(() => {
    installMenu();
    createWindow();
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on('window-all-closed', async () => {
    try {
      await engine?.close();
    } finally {
      app.quit();
    }
  });
}
