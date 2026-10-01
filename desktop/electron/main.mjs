import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { app, BrowserWindow, ipcMain, shell, Menu, screen, safeStorage, Tray, Notification, nativeImage, powerMonitor, dialog } from 'electron';
import fs from 'node:fs';
import { DesktopEngine } from './engine.mjs';
import { windowChrome } from './window-chrome.mjs';
import { loadWindowState, saveWindowState, visibleBounds } from './window-state.mjs';
import { islandBounds, islandCoord, islandSizeFor, islandYFor, ISLAND_VIEW_PETIT, ISLAND_VIEW_TUCKED } from './island.mjs';
import { menuTemplate } from './menu.mjs';
import { setupUpdater } from './updater.mjs';
import { renderPdfPages } from './pdf-render.mjs';
import { IPC_CONTRACT } from '../shared/version.mjs';
import { CONFIG_DIR } from '../../src/core/config.mjs';
import { shutdownFileToolWorkers } from '../../src/tooling/tool-worker.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const APP_NAME = 'Ankita';
const APP_ID = 'com.ankita.desktop';
const isDev = Boolean(process.env.ANKITA_DESKTOP_DEV_URL);
const isPortable = Boolean(process.env.PORTABLE_EXECUTABLE_DIR);
const windowStateFile = () => path.join(app.getPath('userData'), 'window-state.json');

let window = null;
let island = null;
let islandAnchorCX = null;
let engine = null;
let updater = null;
let saveTimer = null;
let crashes = 0;
let tray = null;
let quitting = false;
let drainingQuit = false;
const TRAY_ICON_PATH = '../build/icon.png'; // Packaged with the app; no external runtime dependency.
const TRAY_ICON_SIZE = 18; // Pixels for native menu-bar/taskbar rendering.
function showWindow() { if (!window) return; hideIsland(); if (window.isMinimized()) window.restore(); window.show(); window.focus(); }
function installTray() {
  if (tray) return;
  tray = new Tray(nativeImage.createFromPath(path.resolve(here, TRAY_ICON_PATH)).resize({ width: TRAY_ICON_SIZE, height: TRAY_ICON_SIZE }));
  tray.setToolTip(`${APP_NAME} — scheduled jobs keep running here`);
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Show Ankita', click: showWindow },
    { label: 'Pause all jobs', click: () => engine?.schedule().pauseAll() },
    { type: 'separator' }, { label: 'Quit — stop jobs', click: () => app.quit() },
  ]));
  tray.on('double-click', showWindow);
}
function hideToTray() {
  installTray(); window?.hide();
  if (!engine?.desktopSettings.data.trayNoticeSeen) {
    engine?.desktopSettings.update({ trayNoticeSeen: true });
    if (Notification.isSupported()) new Notification({ title: APP_NAME, body: 'Ankita is running in the tray. Scheduled jobs continue. Choose Quit in the tray to stop them.' }).show();
  }
}

// The companion island stands in for the main window while it is not visible:
// minimized or hidden to the tray. It never takes focus. It opens as a small
// petit tab and springs into the full home card when clicked.
function islandArea() {
  return window && !window.isDestroyed()
    ? screen.getDisplayNearestPoint({ x: window.getBounds().x, y: window.getBounds().y }).workArea
    : screen.getPrimaryDisplay().workArea;
}
function islandPosition(width) {
  return islandBounds(islandArea(), width);
}
function createIsland() {
  const size = islandSizeFor(ISLAND_VIEW_PETIT, 0);
  const at = islandPosition(size.width);
  island = new BrowserWindow({
    width: size.width, height: size.height, x: at.x, y: at.y,
    transparent: true, frame: false, resizable: false,
    minimizable: false, maximizable: false, closable: false,
    // thickFrame draws the standard Windows frame glow around a frameless
    // window — on a transparent island it shows as a milky halo, so it goes
    // off too (the island is fixed-size, nothing to resize anyway).
    thickFrame: false,
    skipTaskbar: true, focusable: false, fullscreenable: false,
    alwaysOnTop: true, show: false, title: `${APP_NAME} island`,
    // No native DWM shadow: on a transparent window it renders as a milky
    // halo around the pill instead of a shadow.
    hasShadow: false,
    webPreferences: {
      preload: path.join(here, 'preload.cjs'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
      spellcheck: false,
    },
  });
  island.on('closed', () => { island = null; });
  if (isDev) {
    void island.loadURL(`${process.env.ANKITA_DESKTOP_DEV_URL}/island.html`);
  } else {
    void island.loadFile(path.join(here, '../renderer/dist/island.html'));
  }
}
function showIsland() {
  if (quitting) return;
  // Exactly one island, always: rebuild from scratch on every appearance so a
  // stuck, drifted or duplicated window from an earlier state can never linger.
  if (island && !island.isDestroyed()) island.destroy();
  island = null;
  createIsland();
  if (!island || island.isDestroyed()) return;
  const size = islandSizeFor(ISLAND_VIEW_PETIT, 0);
  const at = islandPosition(size.width);
  // Appear tucked above the edge with a sliver showing, Coucou-style.
  const tuckedY = islandYFor(ISLAND_VIEW_TUCKED, at.y);
  island.setPosition(at.x, tuckedY - 18);
  island.setSize(size.width, size.height);
  island.showInactive();
  logIslandGeometry('show', { x: at.x, y: tuckedY, width: size.width, height: size.height });
  try {
    const scale = screen.getPrimaryDisplay().scaleFactor || 1;
    fs.appendFileSync(
      path.join(app.getPath('userData'), 'island-geometry.log'),
      `${new Date().toISOString()} env electron=${process.versions.electron} scale=${scale}\n`,
    );
  } catch {
    // Diagnostics only.
  }
  // Lock the horizontal centre for this appearance: every later size reuses it,
  // so repeated expands can never walk the window sideways even if the display
  // query jitters between clicks. Recomputed on the next show.
  islandAnchorCX = at.x + size.width / 2;
  slideIslandTo(at.x, tuckedY);
  startCursorFeed();
}
function hideIsland() {
  stopCursorFeed();
  if (!island || island.isDestroyed() || !island.isVisible()) return;
  if (quitting) { island.hide(); return; }
  // Slide up out of view, then hide — the exit mirrors the entrance.
  const bounds = island.getBounds();
  slideIslandTo(bounds.x, bounds.y - 24, () => { if (island && !island.isDestroyed()) island.hide(); });
}

// Island motion, position-only by design: the window slides (ease-out cubic)
// but its size always snaps instantly to an exact preset — shapes never morph,
// so geometry can never drift or distort. Content motion stays in CSS.
const ISLAND_SLIDE_MS = 240;
const ISLAND_SLIDE_FPS = 60;
let islandSlideTimer = null;
let islandSlideToken = 0;
function slideIslandTo(x, y, done, width, height) {
  if (!island || island.isDestroyed()) { done?.(); return; }
  if (islandSlideTimer) { clearInterval(islandSlideTimer); islandSlideTimer = null; }
  const token = ++islandSlideToken;
  const bounds = island.getBounds();
  const fromX = bounds.x;
  const fromY = bounds.y;
  // Size is re-asserted on every tick via setBounds: on Windows a lone
  // setSize() followed by position-only setPosition() ticks can lose the
  // shrink (368→240 settles back at 368), leaving the island elongated
  // after collapse. Callers without an explicit size hold the current one.
  const targetW = width ?? bounds.width;
  const targetH = height ?? bounds.height;
  const applyBounds = (px, py) => {
    if (!island || island.isDestroyed()) return;
    island.setBounds({
      x: islandCoord(px, x),
      y: islandCoord(py, y),
      width: targetW,
      height: targetH,
    });
  };
  if (Math.abs(fromX - x) < 0.5 && Math.abs(fromY - y) < 0.5) { applyBounds(x, y); done?.(); return; }
  const started = Date.now();
  islandSlideTimer = setInterval(() => {
    if (!island || island.isDestroyed() || token !== islandSlideToken) {
      clearInterval(islandSlideTimer);
      islandSlideTimer = null;
      return;
    }
    const p = Math.min(1, (Date.now() - started) / ISLAND_SLIDE_MS);
    const eased = 1 - Math.pow(1 - p, 3);
    // Coordinates stay int32-safe: interpolation crossing zero yields -0
    // (Math.round(-0.4) is -0), which Electron's converter rejects and which
    // used to crash the main process from inside this tick.
    applyBounds(
      fromX + (x - fromX) * eased,
      fromY + (y - fromY) * eased,
    );
    if (p >= 1) {
      clearInterval(islandSlideTimer);
      islandSlideTimer = null;
      if (island && !island.isDestroyed()) {
        applyBounds(x, y);
        try {
          const settled = island.getBounds();
          const content = island.getContentBounds();
          logIslandGeometry('settled', {
            x: settled.x, y: settled.y, width: settled.width, height: settled.height,
          });
          logIslandGeometry('content', {
            x: content.x, y: content.y, width: content.width, height: content.height,
          });
        } catch {
          // Read-back is diagnostics only.
        }
      }
      if (token === islandSlideToken) done?.();
    }
  }, 1000 / ISLAND_SLIDE_FPS);
}

// Every island resize is recorded here so a drifting window can be diagnosed
// from data instead of screenshots. Safe to delete at any time.
function logIslandGeometry(action, rect) {
  try {
    const line = `${new Date().toISOString()} ${action} ${rect.width}x${rect.height}@${rect.x},${rect.y}\n`;
    fs.appendFileSync(path.join(app.getPath('userData'), 'island-geometry.log'), line);
  } catch {
    // Logging must never break the island.
  }
}

// Streams the pointer position (relative to the island window) so the mascot's
// eyes can follow the cursor. Only runs while the island is visible.
const ISLAND_CURSOR_MS = 50;
let cursorTimer = null;
function startCursorFeed() {
  if (cursorTimer) return;
  cursorTimer = setInterval(() => {
    if (!island || island.isDestroyed() || !island.isVisible()) return;
    const cursor = screen.getCursorScreenPoint();
    const bounds = island.getBounds();
    try {
      // The frame can be mid-reload (dev HMR, window rebuild): a failed send
      // is routine, the next tick retries.
      island.webContents.send('island:cursor', { x: cursor.x - bounds.x, y: cursor.y - bounds.y });
    } catch {
      // Ephemeral send failure only.
    }
  }, ISLAND_CURSOR_MS);
}
function stopCursorFeed() {
  if (cursorTimer) { clearInterval(cursorTimer); cursorTimer = null; }
}

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
  if (updater?.isDownloading?.()) return;
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
  window.on('close', event => { persistWindowState(); if (!quitting) { event.preventDefault(); hideToTray(); showIsland(); } });
  window.on('minimize', () => { if (!quitting) { hideToTray(); showIsland(); } });
  window.on('show', hideIsland);
  window.on('restore', hideIsland);
  window.on('focus', hideIsland);
  window.on('closed', () => { window = null; });

  if (isDev) {
    void window.loadURL(process.env.ANKITA_DESKTOP_DEV_URL);
  } else {
    void window.loadFile(path.join(here, '../renderer/dist/index.html'));
  }

  engine = new DesktopEngine({
    safeStorage,
    // Composio keyless sign-in opens the system browser from the main process.
    openExternal: url => openExternal(url),
    emit: event => {
      if (window && !window.isDestroyed()) window.webContents.send('engine:event', event);
      if (island && !island.isDestroyed()) island.webContents.send('engine:event', event);
      if (tray && event.type === 'schedule-changed') tray.setToolTip(`${APP_NAME} — ${event.jobs.filter(job => job.running).length} running, ${event.jobs.filter(job => job.needsApproval).length} need approval`);
      if ((event.type === 'routine-failed' || (event.type === 'approval-request' && event.routineId)) && (!window?.isVisible() || !window?.isFocused()) && Notification.isSupported()) {
        const notification = new Notification({ title: event.type === 'routine-failed' ? 'Scheduled job needs attention' : 'Scheduled job needs approval', body: event.detail || event.text || 'Open Ankita to review the job.' });
        notification.on('click', showWindow); notification.show();
      }
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

ipcMain.handle('engine:invoke', async (event, action, payload) => {
  // Both of our own windows may call: the main window and the island.
  // Anything else (a popup, a second frame) is rejected.
  const fromMain = window && event.sender === window.webContents;
  const fromIsland = island && event.sender === island.webContents;
  if ((!fromMain && !fromIsland) || event.senderFrame !== event.sender.mainFrame) throw new Error('Desktop IPC is restricted to the application windows');
  const current = requiredEngine();
  if (action === 'initialize') {
    await current.init();
    try { await current.schedule().start(); }
    catch (error) { current.emit({ type: 'scheduler-error', message: error.message }); }
    installTray();
    return {
      teammates: current.listTeammates(),
      models: current.listModels(),
      settings: current.getSettingsSummary(),
      preferences: current.getDesktopPreferences(),
      version: app.getVersion(),
      contract: IPC_CONTRACT,
      chrome: windowChrome().controls,
      jobs: current.schedule().list(),
    };
  }
  await current.init();
  switch (action) {
    case 'palette:query': return current.paletteQuery(payload?.query);
    case 'palette:run': return current.paletteRun(payload?.id, payload?.threadId);
    case 'redact': return current.secretHistory.clean(String(payload?.text || ''));
    case 'secretList': return current.secureStore.listSecrets();
    case 'secretRemove': return current.secureStore.remove(payload?.id);
    case 'exportChat': {
      const format = payload?.format === 'json' ? 'json' : 'md';
      const content = current.exportChat(payload?.id, format);
      const result = await dialog.showSaveDialog(window, { title: 'Export conversation', defaultPath: `${payload?.id || 'conversation'}.${format}`, filters: [{ name: format === 'json' ? 'JSON' : 'Markdown', extensions: [format] }] });
      if (result.canceled || !result.filePath) return { cancelled: true };
      fs.writeFileSync(result.filePath, content, { encoding: 'utf8', mode: 0o600 });
      return { saved: true };
    }
    case 'scheduleList': return current.schedule().list(payload?.threadId);
    case 'scheduleStatus': return current.schedule().status(payload?.threadId);
    case 'scheduleAdd': return current.schedule().add(payload);
    case 'scheduleUpdate': return current.schedule().update(payload.id, payload.patch);
    case 'scheduleRemove': return current.schedule().remove(payload.id);
    case 'scheduleEnable': return current.schedule().enable(payload.id, payload.enabled);
    case 'scheduleRunNow': return current.schedule().runNow(payload.id);
    case 'scheduleStop': return current.schedule().stopRun(payload.id);
    case 'schedulePauseAll': return current.schedule().pauseAll();
    case 'scheduleHostSettings': {
      if (payload?.startAtLogin !== undefined) {
        const startAtLogin = payload.startAtLogin === true;
        app.setLoginItemSettings({ openAtLogin: startAtLogin }); current.desktopSettings.update({ startAtLogin });
      }
      return { startAtLogin: current.desktopSettings.data.startAtLogin === true, supported: !isPortable };
    }
    case 'listTeammates': return current.listTeammates();
    case 'listProjects': return current.listProjects();
    case 'createProject': return current.createProject(payload);
    case 'updateProject': return current.updateProject(payload.id, payload.patch);
    case 'assignProject': return current.assignProject(payload.id, payload.projectId);
    case 'addProjectTodo': return current.addProjectTodo(payload.id, payload.text);
    case 'addProjectRecord': return current.addProjectRecord(payload.id, payload.kind, payload.text);
    case 'completeProjectTodo': return current.completeProjectTodo(payload.id, payload.ref);
    case 'workspaceSnapshot': return current.workspaceSnapshot(payload.id);
    case 'readGeneratedImage': return current.readGeneratedImage(payload.id, payload.path);
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
    case 'send': return current.send(payload.id, payload.text, payload.attachments);
    case 'renderPdfPages': return renderPdfPages(payload?.data);
    case 'cancel': return current.cancel(payload.id);
    case 'respondApproval': return current.respondApproval(payload.requestId, payload.answer);
    case 'approvalList': return current.listApprovals();
    case 'secureStoreList': return { available: await current.secureStore.available(), records: await current.secureStore.list() };
    case 'secureStoreSave': {
      try { const record = await current.secureStore.save(payload); current.emit({ type: 'secure-store-changed' }); return record; }
      finally { if (payload) payload.password = ''; }
    }
    case 'secureStoreRemove': { const removed = await current.secureStore.remove(payload.id); current.emit({ type: 'secure-store-changed' }); return removed; }
    case 'respondSecureStore': {
      try { return current.credentialRequests.respond(payload); }
      finally { if (payload) payload.password = ''; }
    }
    case 'listModels': return current.listModels();
      case 'listSkills': return current.listSkills();
      case 'setSkillEnabled': return current.setSkillEnabled(payload.name, payload.enabled);
    case 'setModel': return current.setModel(payload.id, payload.modelId);
    case 'settingsSummary': return current.getSettingsSummary();
    case 'getDesktopPreferences': return current.getDesktopPreferences();
    case 'saveDesktopSettings': return current.saveDesktopSettings(payload);
    case 'testCustomProvider': return current.testCustomProvider(payload);
    case 'getChannels': return current.getChannels();
    case 'saveChannelSettings': return current.saveChannelSettings(payload.channel, payload.patch);
    case 'testTelegramChannel': return current.testTelegramChannel(payload);
    case 'pluginsOverview': return current.plugins.overview();
    case 'pluginsCatalog': return current.plugins.catalog(payload);
    case 'pluginsConnect': return current.plugins.connect(payload);
    case 'pluginsDisconnectAccount': return current.plugins.disconnectAccount(payload);
    case 'pluginsDisconnectService': return current.plugins.disconnectService(payload);
    case 'pluginsRefresh': return current.refreshPlugins();
    case 'browserPluginsOverview': return current.browserPlugins.overview();
    case 'browserPluginSetEnabled': return current.browserPlugins.setEnabled(payload);
    case 'browserPluginSetHeadless': return current.browserPlugins.setHeadless(payload);
    case 'browserPluginSiteRule': return current.browserPlugins.changeSiteRule(payload);
    case 'browserPluginConfigureChrome': return current.browserPlugins.configureChrome(payload);
    case 'browserPluginStartChrome': return current.browserPlugins.startChrome();
    case 'browserPluginTestChromePort': return current.browserPlugins.testChromePort(payload);
    case 'browserPluginInstallChromium': return current.browserPlugins.installChromium();
    case 'browserSessionView': return current.browserScope(payload?.scope).view();
    case 'browserSessionStop': return payload?.scope ? current.schedule().stopRun(payload.scope.replace(/^job:/, '')) : current.browserManager.close({ includeScopes: false });
    case 'browserSessionTakeover': return current.browserScope(payload?.scope).takeover(payload?.enabled === true);
    case 'browserSessionInput': return current.browserScope(payload?.scope).userInput(payload);
    case 'browserSessionSelectTab': return current.browserScope(payload?.scope).selectTab(payload?.tab);
    case 'appInfo': return { version: app.getVersion(), contract: IPC_CONTRACT };
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

ipcMain.handle('island:action', (_event, action) => {
  if (action === 'show-main') { showWindow(); return true; }
  // The island asks for a size preset as it flips between petit tab and home
  // card. Sizes snap instantly (shapes never morph); only the y position
  // slides, e.g. tucking back above the edge.
  if (!island || island.isDestroyed()) return false;
  const size = action === 'petit' ? islandSizeFor('petit', 0)
    : action === 'home' ? islandSizeFor('home', 0)
    : action === 'home-expanded' ? islandSizeFor('home-expanded', 1)
    : action === 'tuck' ? islandSizeFor('petit', 0)
    : null;
  if (!size) return false;
  const at = islandPosition(size.width);
  const y = action === 'tuck' ? islandYFor('tucked', at.y) : at.y;
  // Centre comes from the session anchor, never a fresh display query.
  const x = islandAnchorCX == null ? at.x : Math.round(islandAnchorCX - size.width / 2);
  island.setSize(size.width, size.height);
  logIslandGeometry(action, { x, y, width: size.width, height: size.height });
  slideIslandTo(x, y, undefined, size.width, size.height);
  return true;
});

ipcMain.handle('open-external', (_event, value) => openExternal(value));

ipcMain.handle('app:action', (_event, action) => {
  if (action === 'open-config-folder') return shell.openPath(CONFIG_DIR);
  if (action === 'open-data-folder') return shell.openPath(app.getPath('userData'));
  // Recovery for a window/main version mismatch: relaunching picks up whatever
  // is on disk now, so a half-applied update finishes instead of staying stuck.
  if (action === 'relaunch') {
    app.relaunch();
    app.quit(); // before-quit drains jobs and releases ownership before restart.
    return true;
  }
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
  // The resident filesystem-inspection worker must not outlive the app.
  app.on('will-quit', shutdownFileToolWorkers);
  app.on('before-quit', event => {
    if (quitting) return;
    event.preventDefault(); if (drainingQuit) return; drainingQuit = true;
    hideIsland();
    stopCursorFeed();
    void Promise.resolve(engine?.close()).finally(() => { quitting = true; tray?.destroy(); tray = null; app.quit(); });
  });
  app.on('second-instance', () => {
    if (!window) return;
    if (window.isMinimized()) window.restore();
    window.show();
    window.focus();
  });

  app.whenReady().then(() => {
    installMenu();
    createWindow();
    powerMonitor.on('lock-screen', () => { if (engine?.scheduler) engine.scheduler.foregroundAvailable = false; });
    powerMonitor.on('unlock-screen', () => { if (engine?.scheduler) engine.scheduler.foregroundAvailable = true; });
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on('window-all-closed', () => { if (quitting) app.quit(); });
}
