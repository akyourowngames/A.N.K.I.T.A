import electronUpdater from 'electron-updater';

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

export function setupUpdater({ isPackaged = false, isDev = false, isPortable = false, emit = () => {}, updater = null, stallMs = 90_000 } = {}) {
  const usable = isPackaged && !isDev && !isPortable;
  if (!usable) {
    return { usable: false, check: () => Promise.resolve(false), install: () => false, isDownloading: () => false };
  }

  updater ||= electronUpdater.autoUpdater;

  updater.autoDownload = true;
  updater.autoInstallOnAppQuit = true;

  let stallTimer = null;
  let downloading = false;
  let checkInFlight = null;
  let percent = 0;
  let version = '';
  const clearStall = () => { if (stallTimer) clearTimeout(stallTimer); stallTimer = null; };
  const armStall = () => {
    clearStall();
    stallTimer = setTimeout(() => emit({ type: 'stalled', percent, version }), stallMs);
    stallTimer.unref?.();
  };

  updater.on('checking-for-update', () => { if (!downloading) emit({ type: 'checking' }); });
  updater.on('update-available', info => { downloading = true; version = describe(info).version || ''; percent = 0; emit({ type: 'available', ...describe(info) }); armStall(); });
  updater.on('update-not-available', () => { if (downloading) return; clearStall(); emit({ type: 'current' }); });
  updater.on('download-progress', progress => { downloading = true; percent = Math.max(0, Math.min(100, Math.round(progress.percent || 0))); emit({ type: 'progress', percent }); armStall(); });
  updater.on('update-downloaded', info => { downloading = false; clearStall(); emit({ type: 'downloaded', ...describe(info) }); });
  updater.on('error', error => { downloading = false; clearStall(); emit({ type: 'error', message: String(error?.message || error) }); });

  const check = () => {
    if (downloading) return Promise.resolve(true);
    if (checkInFlight) return checkInFlight;
    checkInFlight = (async () => {
      try {
        await updater.checkForUpdates();
        return true;
      } catch (error) {
        downloading = false;
        clearStall();
        emit({ type: 'error', message: String(error?.message || error) });
        return false;
      } finally { checkInFlight = null; }
    })();
    return checkInFlight;
  };

  const install = () => {
    try {
      updater.quitAndInstall();
      return true;
    } catch {
      return false;
    }
  };

  return { usable: true, check, install, isDownloading: () => downloading, autoUpdater: updater };
}
