/**
 * The renderer <-> main process contract.
 *
 * The window (renderer) and the background service (main) are built together,
 * so in a healthy build they always agree. A mismatch means a stale or
 * half-applied build - an old main talking to a new window, or the reverse -
 * which otherwise shows up as confusing errors like "Unknown desktop setting".
 *
 * Bump CONTRACT whenever the IPC surface changes in a way an older counterpart
 * cannot understand. The app version alone is not enough: a partial rebuild can
 * leave both halves reporting the same package.json version while their code
 * differs, so the contract is what actually detects it.
 */
export const IPC_CONTRACT = 4;

/**
 * Compare the window's build identity with the background service's.
 * Pure, so the app and its tests share one definition of "in sync".
 */
export function checkCompat(main = {}, renderer = {}) {
  const rendererVersion = String(renderer.version || 'unknown');
  const mainVersion = String(main.version || 'unknown');
  const base = { rendererVersion, mainVersion };
  const rendererContract = Number(renderer.contract);
  const mainContract = Number(main.contract);

  // An old main process does not report a contract at all - that is itself the
  // mismatch, not a reason to stay quiet.
  if (!Number.isFinite(rendererContract) || !Number.isFinite(mainContract)) {
    return {
      ok: false,
      code: 'contract',
      detail: "This window and Ankita's background service are different builds. Restart Ankita to recover.",
      ...base,
    };
  }
  if (rendererContract !== mainContract) {
    return {
      ok: false,
      code: 'contract',
      detail: `This window and Ankita's background service are incompatible builds (window ${rendererVersion}, service ${mainVersion}). Restart to finish updating.`,
      ...base,
    };
  }
  if (rendererVersion !== mainVersion) {
    return {
      ok: false,
      code: 'version',
      detail: `This window is ${rendererVersion} but Ankita's background service is ${mainVersion}. Restart to finish updating.`,
      ...base,
    };
  }
  return { ok: true, code: 'ok', detail: '', ...base };
}
