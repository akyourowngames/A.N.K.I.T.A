const SENSITIVE_KEY = /(?:api[_-]?key|token|secret|password|passwd|auth|credential|cookie|private[_-]?key)/i;

/** Exact configured credentials complement pattern matching for opaque values. */
export function configuredSecrets(...records) {
  return [...new Set(records.flatMap(record => Object.entries(record || {})
    .filter(([key, value]) => SENSITIVE_KEY.test(key) && typeof value === 'string' && value)
    .flatMap(([, value]) => [value, ...value.split(/\r?\n/).filter(Boolean)])))];
}

/** Redact display text; the original arguments and transport payloads stay intact. */
export function redactText(value, { secrets = [] } = {}) {
  let text = String(value ?? '');
  for (const secret of [...new Set(secrets)].filter(Boolean).sort((a, b) => b.length - a.length)) {
    text = text.split(String(secret)).join('[REDACTED]');
    text = text.split(JSON.stringify(String(secret)).slice(1, -1)).join('[REDACTED]');
  }
  text = text.replace(/\b(Bearer|Basic)\s+[^\s"',;]+/gi, '$1 [REDACTED]');
  // JSON fields, environment assignments, URL query parameters and CLI flags.
  text = text.replace(/(?<![\w.-])((?:["']?[\w.-]*(?:api[_-]?key|token|secret|password|passwd|authorization|credential|cookie|private[_-]?key)[\w.-]*["']?\s*[:=]\s*)|(?:--[\w.-]*(?:api[_-]?key|token|secret|password|passwd|authorization|credential|cookie|private[_-]?key)[\w.-]*\s+))(?:("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|([^\s&,;\}\]]+))/gi,
    (_match, prefix, quoted) => `${prefix}${quoted ? quoted[0] + '[REDACTED]' + quoted[0] : '[REDACTED]'}`);
  text = text.replace(/(https?:\/\/)[^\s/@]+:[^\s/@]+@/gi, '$1[REDACTED]@');
  text = text.replace(/\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{16,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b/g, '[REDACTED]');
  return text;
}
