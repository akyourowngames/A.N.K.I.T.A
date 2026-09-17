import { capOutput } from '../tools/_shared.mjs';

/** Discard malformed/orphan tool messages from interrupted saved sessions. */
export function sanitizeMessages(messages) {
  if (!Array.isArray(messages)) throw new Error('Session messages must be an array.');
  const out = [];
  for (let i = 0; i < messages.length; i++) {
    const m = messages[i];
    if (!m || !['user', 'assistant', 'system', 'tool'].includes(m.role)) continue;
    if (m.role === 'tool') continue;
    const content = typeof m.content === 'string' ? m.content : null;
    if (m.role === 'assistant' && Array.isArray(m.tool_calls) && m.tool_calls.length) {
      const calls = m.tool_calls;
      const ids = new Set(calls.map(c => c?.id));
      const replies = [];
      let j = i + 1;
      while (messages[j]?.role === 'tool') replies.push(messages[j++]);
      const valid = ids.size === calls.length && calls.every(c => typeof c?.id === 'string' && c.id &&
        c.type === 'function' && typeof c.function?.name === 'string' && typeof c.function?.arguments === 'string') &&
        replies.length === calls.length && new Set(replies.map(r => r.tool_call_id)).size === calls.length &&
        replies.every(r => ids.has(r.tool_call_id) && typeof r.content === 'string');
      if (valid) {
        out.push({ role: 'assistant', content, tool_calls: calls.map(c => ({ id: c.id, type: 'function', function: { name: c.function.name, arguments: c.function.arguments } })) });
        out.push(...replies.map(r => ({ role: 'tool', tool_call_id: r.tool_call_id, content: capOutput(r.content) })));
      } else if (content) out.push({ role: 'assistant', content: content + '\n[Incomplete tool calls removed from restored session.]' });
      i = j - 1;
    } else if (content !== null) out.push({ role: m.role, content });
  }
  return out;
}

function groups(messages) {
  const out = [];
  for (let i = 0; i < messages.length; i++) {
    const group = [messages[i]];
    if (messages[i].tool_calls) while (messages[i + 1]?.role === 'tool') group.push(messages[++i]);
    out.push(group);
  }
  return out;
}

/** Count messages, preserve the current task, and remove tool exchanges atomically. */
export function trimMessages(messages, maxMessages = 40, maxBytes = Infinity) {
  const clean = sanitizeMessages(messages);
  const system = clean[0]?.role === 'system' ? clean.shift() : { role: 'system', content: '' };
  const max = Math.max(2, Number(maxMessages) || 40);
  let userIndex = -1;
  for (let i = clean.length - 1; i >= 0; i--) if (clean[i].role === 'user') { userIndex = i; break; }
  const anchor = userIndex < 0 ? null : clean[userIndex];
  const candidates = groups(clean.filter((_, i) => i !== userIndex));
  let selected = [];
  let count = anchor ? 1 : 0;
  for (let i = candidates.length - 1; i >= 0; i--) {
    if (count + candidates[i].length > max) break;
    selected.unshift(candidates[i]);
    count += candidates[i].length;
  }
  // Preserve chronological ordering around the anchored user message.
  const assemble = () => {
    const keep = new Set(selected.flat());
    if (anchor) keep.add(anchor);
    return [system, ...clean.filter(m => keep.has(m))];
  };
  let result = assemble();
  const size = () => Buffer.byteLength(JSON.stringify(result));
  while (size() > maxBytes && selected.length > 1) { selected.shift(); result = assemble(); }
  if (size() > maxBytes) {
    result = result.map(m => ({ ...m }));
    const editable = result.filter(m => typeof m.content === 'string' && m.role !== 'system');
    for (const m of editable.sort((a, b) => b.content.length - a.content.length)) {
      const excess = size() - maxBytes;
      if (excess <= 0) break;
      m.content = capOutput(m.content, Math.max(128, Buffer.byteLength(m.content) - excess - 64));
    }
  }
  if (size() > maxBytes) throw new Error('The current request/tool schema exceeds the model context budget. Use a larger context model or clear/reduce the request.');
  return result;
}
