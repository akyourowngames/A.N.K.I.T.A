/**
 * Network failures worth waiting out. Everything else with a cause code —
 * DNS misses (ENOTFOUND/EAI_AGAIN), refused connections, TLS errors — fails
 * fast instead of burning ~7s of pointless retries.
 */
const RETRYABLE_CAUSE = new Set([
  "ETIMEDOUT",
  "ECONNRESET",
  "ECONNABORTED",
  "EPIPE",
  "UND_ERR_CONNECT_TIMEOUT",
  "UND_ERR_SOCKET",
  "UND_ERR_HEADERS_TIMEOUT",
  "UND_ERR_BODY_TIMEOUT",
]);

function abortError(signal) {
  if (signal?.reason instanceof Error) return signal.reason;
  const err = new Error("The operation was aborted.");
  err.name = "AbortError";
  return err;
}

/** setTimeout that rejects immediately when the caller's signal fires. */
function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(abortError(signal));
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(abortError(signal));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * fetch() with backoff for 429 and 5xx. Honors Retry-After when present.
 * Pass an AbortSignal via opts.signal to cancel, including mid-backoff.
 * `maxDelayMs` caps any single wait so one-shot runs stay snappy.
 */
export async function fetchWithRetry(url, opts = {}, { retries = 3, maxDelayMs = 8000, onRetry } = {}) {
  let lastError;
  for (let attempt = 0; attempt <= retries; attempt++) {
    if (opts.signal?.aborted) throw abortError(opts.signal);
    try {
      const res = await fetch(url, opts);
      const retryable = res.status === 429 || res.status >= 500;
      if (!retryable || attempt === retries) return res;

      const after = Number(res.headers.get("retry-after"));
      const waitMs = Math.min(
        Number.isFinite(after) && after > 0 ? after * 1000 : 700 * 2 ** attempt,
        Math.max(0, maxDelayMs)
      );
      try {
        await res.body?.cancel();
      } catch {}
      onRetry?.(res.status, waitMs);
      await sleep(waitMs, opts.signal);
    } catch (err) {
      if (err.name === "AbortError") throw err;
      lastError = err;
      const code = err?.cause?.code;
      const retryable = code === undefined || RETRYABLE_CAUSE.has(code);
      if (!retryable || attempt === retries) throw err;
      await sleep(Math.min(700 * 2 ** attempt, Math.max(0, maxDelayMs)), opts.signal);
    }
  }
  throw lastError;
}
