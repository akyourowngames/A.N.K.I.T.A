import { isReadOnly, needsApproval } from '../../tools/index.mjs';

const FAILURE_RE = /^(Error\b|Not run:|The user denied|Action cancelled)/i;
const READ_ACTION_RE = /(?:^|_)(GET|FETCH|LIST|SEARCH|QUERY|LOOKUP|READ|DOWNLOAD|RETRIEVE|FIND|DESCRIBE)(?:_|$)/i;
const GMAIL_SEND_RE = /^GMAIL_.*SEND/i;
const DRIVE_CREATE_RE = /^(GOOGLEDRIVE|GOOGLEDOCS)_.*(UPLOAD|CREATE)/i;

export function isToolFailure(resultText) {
  return FAILURE_RE.test(String(resultText));
}

function composioActions(toolName, args) {
  if (!/^mcp__composio__COMPOSIO_MULTI_EXECUTE_TOOL$/i.test(toolName)) return null;
  return Array.isArray(args?.tools) ? args.tools.map(tool => String(tool?.tool_slug || '').toUpperCase()) : [];
}

export function isMutation(toolName, args = {}, mcp = null) {
  if (toolName === 'composio') return !['status', 'list', 'accounts', 'search'].includes(String(args?.action || 'status').toLowerCase());
  if (String(toolName).startsWith('mcp__')) {
    const actions = composioActions(toolName, args);
    if (actions) return !actions.length || actions.some(action => !READ_ACTION_RE.test(action));
    if (/^mcp__composio__COMPOSIO_(SEARCH_TOOLS|GET_TOOL_SCHEMAS)$/i.test(toolName)) return false;
    const found = mcp?.findTool?.(toolName);
    if (found?.tool?.annotations?.readOnlyHint === true) return false;
    return mcp?.needsApproval?.(toolName) === true || found !== null;
  }
  return needsApproval(toolName, args) || !isReadOnly(toolName, args);
}

function parseResult(text) {
  try { return JSON.parse(String(text)); } catch { return null; }
}

function entries(value, key, depth = 0) {
  if (!value || typeof value !== 'object' || depth > 10) return [];
  const found = [];
  for (const [field, child] of Object.entries(value)) {
    if (field === key) found.push(child);
    if (child && typeof child === 'object') found.push(...entries(child, key, depth + 1));
  }
  return found;
}

function serviceResult(payload, action, index, batched) {
  if (!batched) return payload?.data || payload;
  const rows = payload?.data?.results || payload?.results;
  if (!Array.isArray(rows)) return null;
  const row = rows.find((item, position) => Number(item?.index ?? position) === index);
  if (row?.tool_slug && String(row.tool_slug).toUpperCase() !== action) return null;
  return row?.response?.data || row?.response || null;
}

function hasFailure(payload, text) {
  if (payload) {
    if (entries(payload, 'error_count').some(value => Number(value) > 0)) return true;
    if (entries(payload, 'successful').includes(false) || entries(payload, 'isError').includes(true) || entries(payload, 'ok').includes(false)) return true;
    if (entries(payload, 'error').some(value => value !== null && value !== false && value !== '')) return true;
  }
  return /error_count["\\]?\s*(?::|=)\s*[1-9]|successful["\\]?\s*(?::|=)\s*false|isError["\\]?\s*(?::|=)\s*true|ok["\\]?\s*(?::|=)\s*false/i.test(text);
}

export function verdictFor(toolName, args = {}, resultText = '', mcp = null) {
  if (!isMutation(toolName, args, mcp)) return null;
  const text = String(resultText);
  if (isToolFailure(text)) return { ok: false, reason: 'tool reported a failure', evidence: '' };
  const payload = parseResult(text);
  if (hasFailure(payload, text)) return { ok: false, reason: 'tool response contains a failure; check the result and run a read-back', evidence: '' };

  const batchActions = composioActions(toolName, args);
  const actions = batchActions || [String(toolName).split('__').at(-1).toUpperCase()];
  const tools = batchActions ? args.tools : [args];
  const verdicts = actions.flatMap((action, index) => {
    if (READ_ACTION_RE.test(action)) return [];
    const item = serviceResult(payload, action, index, Boolean(batchActions));
    if (GMAIL_SEND_RE.test(action)) {
      const tool = tools[index];
      const input = tool?.arguments || tool;
      const requestedAttachment = ['attachments', 'attachment', 'attachment_ids', 'attachmentIds', 'file_path', 'filePath']
        .some(key => Array.isArray(input?.[key]) ? input[key].length > 0 : Boolean(input?.[key]));
      if (!requestedAttachment) return [{ ok: null, reason: 'send receipt needs a read-back of the sent message', evidence: '' }];
      const hasFiles = entries(item, 'attachmentList').some(list => Array.isArray(list) && list.length > 0);
      return [hasFiles
        ? { ok: true, reason: '', evidence: 'attachmentList is non-empty; fetch sent message to confirm delivery' }
        : { ok: false, reason: 'no attachment evidence in tool result — fetch the sent message and check before claiming it was attached', evidence: '' }];
    }
    if (DRIVE_CREATE_RE.test(action)) {
      const receipt = ['id', 'fileId', 'file_id', 'documentId', 'document_id', 'webViewLink', 'link', 'url']
        .some(key => typeof item?.[key] === 'string' && item[key].trim());
      return [receipt
        ? { ok: true, reason: '', evidence: 'file ID or link returned; read back content before claiming it is populated' }
        : { ok: false, reason: 'no file ID or link in tool result — check the file before claiming it was created', evidence: '' }];
    }
    return [{ ok: null, reason: 'side effect needs a read-back check before claiming success', evidence: '' }];
  });
  return verdicts.find(verdict => verdict.ok === false)
    || verdicts.find(verdict => verdict.ok === null)
    || verdicts[0]
    || { ok: null, reason: 'side effect needs a read-back check before claiming success', evidence: '' };
}

export function verificationFooter(verdict) {
  if (!verdict) return '';
  if (verdict.ok === true) return `\n[verified: ${String(verdict.evidence || 'tool receipt').replace(/\s+/g, ' ').slice(0, 150)}]`;
  const reason = String(verdict.reason || 'side effect is unconfirmed').replace(/\s+/g, ' ').slice(0, 90);
  return `\n[UNVERIFIED: ${reason}. Do not claim success; run a read-back check or report the limitation.]`;
}
