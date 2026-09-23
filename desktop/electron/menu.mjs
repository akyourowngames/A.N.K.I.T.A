/**
 * The application menu. Menu items that need the UI (new teammate, find, toggle
 * sidebar) forward a command name to the focused window over `menu:command`.
 * Plain OS behaviour (copy, zoom, fullscreen, quit) uses Electron roles so it
 * keeps working everywhere without wiring.
 */

export function menuTemplate({ isMac, isDev, send, openConfigFolder, openDataFolder, checkForUpdates, about }) {
  const command = (label, accelerator, name) => ({ label, accelerator, click: () => send(name) });

  const fileMenu = {
    label: 'File',
    submenu: [
      command('New teammate', 'CmdOrCtrl+N', 'new-teammate'),
      command('Find teammate', 'CmdOrCtrl+K', 'find'),
      command('Settings', 'CmdOrCtrl+,', 'settings'),
      { type: 'separator' },
      isMac ? { role: 'close' } : { role: 'quit' },
    ],
  };

  const viewMenu = {
    label: 'View',
    submenu: [
      ...(isDev ? [{ role: 'reload' }, { role: 'forceReload' }, { role: 'toggleDevTools' }, { type: 'separator' }] : []),
      { role: 'resetZoom' },
      { role: 'zoomIn' },
      { role: 'zoomOut' },
      { type: 'separator' },
      command('Toggle sidebar', 'CmdOrCtrl+B', 'toggle-sidebar'),
      { role: 'togglefullscreen' },
    ],
  };

  const helpMenu = {
    label: 'Help',
    submenu: [
      { label: `About ${about}`, click: () => send('about') },
      { label: 'Check for updates…', click: checkForUpdates },
      { type: 'separator' },
      { label: 'Open config folder', click: openConfigFolder },
      { label: 'Open app data folder', click: openDataFolder },
    ],
  };

  const template = [fileMenu, { role: 'editMenu' }, viewMenu, { role: 'windowMenu' }, helpMenu];

  if (isMac) {
    template.unshift({
      label: about,
      submenu: [
        { label: `About ${about}`, click: () => send('about') },
        { type: 'separator' },
        { role: 'services' },
        { type: 'separator' },
        { role: 'hide' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit' },
      ],
    });
  }

  return template;
}
