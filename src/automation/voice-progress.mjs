const ACTION_LABEL_CHARS = 80; // Characters: bounded names, never file bodies or full paths.
const EXECUTABLE_TOKEN = /^\s*(?:&\s+)?(?:"([^"]+)"|'([^']+)'|([^\s;|&]+))/u;
const SAFE_PROGRAM = /^[\p{L}\p{N}_.-]+$/u; // Program basename only; shell expressions are not narration context.
const RUNNING_COMMAND_RECEIPT = /^job \S+: (?:running|stopping)\b/mu; // Native command receipt: accepted work may still be running after yield_ms.
const basename = value => typeof value === 'string' ? value.replace(/\\/g, '/').split('/').at(-1).replace(/[\x00-\x1f\x7f]/g, '').slice(0, ACTION_LABEL_CHARS) : undefined;

/** Ephemeral facts only. Never copy command arguments, file contents or tool results into narration. */
export function voiceActionContext(call) {
  let args = {};
  try { args = JSON.parse(call?.function?.arguments || '{}') || {}; } catch { /* Incomplete arguments carry no extra facts. */ }
  const token = typeof args.command === 'string' ? args.command.match(EXECUTABLE_TOKEN) : null;
  const program = token ? basename(token[1] || token[2] || token[3]) : undefined;
  return {
    tool: String(call?.function?.name || '').slice(0, ACTION_LABEL_CHARS),
    ...(typeof args.path === 'string' ? { target: basename(args.path) } : {}),
    ...(program && SAFE_PROGRAM.test(program) ? { program, background: args.background === true } : {}),
  };
}

export function voiceResultConfirmation(context, state, result, verdict) {
  if (state === 'failed') return 'failed';
  if (context.tool === 'run_command' && RUNNING_COMMAND_RECEIPT.test(String(result))) context.background = true;
  return context.background ? 'submitted' : verdict?.ok === true ? 'confirmed' : 'reported';
}
