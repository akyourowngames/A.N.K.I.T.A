const MESSAGE_LIMIT = 1024; // Characters: enough for a login error without expanding a compact card indefinitely.
/** Login results contain public metadata only; also preserve session guard errors. */
export function secureStoreReceipt(result) {
  if (!result) return {};
  for (const line of String(result).split('\n')) { try { const value = JSON.parse(line); if (value?.type === 'browser_login') return value; } catch {} }
  return { status: /cancel|denied|stopped/i.test(result) ? 'cancelled' : 'attention', message: String(result).slice(0, MESSAGE_LIMIT) };
}
