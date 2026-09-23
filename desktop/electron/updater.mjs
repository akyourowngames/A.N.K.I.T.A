import electronUpdater from 'electron-updater';

const { autoUpdater } = electronUpdater;

/**
 * Auto-update for installed Windows/macOS builds, fed by GitHub Releases.
 *
 * Only meaningful for the NSIS installer / dmg: the portable exe is a one-file
 * bundle that cannot replace itself, and a dev run has no published feed. In
 * those cases this returns inert no-ops so callers never have to branch.
 *
 * Progress and outcomes are forwarded to the renderer as `update:event`; the
 * renderer decides how loud to be (a background error stays quiet, a downloaded
 * update gets a "restart" prompt).
 */

function describe(info) {
  if (!info) return {};
  return { version: info.version || info.updateInfo?.version, releaseName: info.releaseName || null };
}

export function setupUpdater({ isPackaged = false, isDev = false, isPortable = false, emit = () => {} } = {}) {
  const usable = isPackaged && !isDev && !isPortable;
  if (!usable) {
    return { usable: false, check: () => Promise.resolve(false), install: () => false };
  }

  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('checking-for-update', () => emit({ type: 'checking' }));
  autoUpdater.on('update-available', info => emit({ type: 'available', ...describe(info) }));
  autoUpdater.on('update-not-available', () => emit({ type: 'current' }));
  autoUpdater.on('download-progress', progress => emit({ type: 'progress', percent: Math.round(progress.percent || 0) }));
  autoUpdater.on('update-downloaded', info => emit({ type: 'downloaded', ...describe(info) }));
  autoUpdater.on('error', error => emit({ type: 'error', message: String(error?.message || error) }));

  const check = async () => {
    try {
      await autoUpdater.checkForUpdates();
      return true;
    } catch (error) {
      emit({ type: 'error', message: String(error?.message || error) });
      return false;
    }
  };

  const install = () => {
    try {
      autoUpdater.quitAndInstall();
      return true;
    } catch {
      return false;
    }
  };

  return { usable: true, check, install, autoUpdater };
}
