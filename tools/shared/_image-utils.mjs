/** Combine the turn's cancellation with a hard deadline without leaking timers. */
export function deadlineSignal(parent, timeoutMs) {
  const controller = new AbortController();
  const onAbort = () => controller.abort(parent?.reason || new Error('cancelled'));
  if (parent?.aborted) onAbort();
  else parent?.addEventListener('abort', onAbort, { once: true });
  const timer = setTimeout(() => controller.abort(new Error('timeout')), timeoutMs);
  return {
    signal: controller.signal,
    dispose() {
      clearTimeout(timer);
      parent?.removeEventListener('abort', onAbort);
    },
  };
}

export function safeToolError(error, prefix) {
  if (error?.name === 'AbortError' || error?.name === 'TimeoutError' || error?.message === 'timeout' || error?.message === 'cancelled') {
    return new Error(`${prefix} timed out or was cancelled`);
  }
  return new Error(`${prefix} failed; check the service URL and credentials`);
}
