/**
 * Compare the configured voice planners on identical spoken-style prompts.
 *
 * Measures streamed time-to-first-token (TTFT), first answer token and total
 * completion for "before" (Baseten Muse Spark) and "after" (Modal DeepSeek).
 * The microphone and Sarvam speech path are not involved; `verify-voice-latency`
 * covers transcript-to-player end to end.
 *
 * Usage: node scripts/bench-voice-planner.mjs [--rounds N] [--only before|after]
 */
import { loadConfig } from '../src/core/config.mjs';
import { createVoiceBrain, VOICE_REPLY_INSTRUCTIONS } from '../src/core/voice-session.mjs';
import { configuredSecrets, redactText } from '../src/core/redact.mjs';

const DEFAULT_ROUNDS = 3; // Multiple rounds let a warm server settle; medians drive the report.
const REQUEST_TIMEOUT_MS = 45_000; // Milliseconds: bound a stalled cloud request.
const WARMUP_PROMPT = 'Hi'; // Excluded from medians: a serverless cold start lands here.
const STREAM_END = '[DONE]'; // OpenAI-compatible SSE terminator.
const PROMPTS = [
  'Hello, how are you?',
  'I am good, what about you?',
  'Thanks, that helps.',
  'Workspace mein ek file banao aur usko padhkar batao.',
  'What is the capital of France?',
  'Summarise what you just told me in one line.',
];
const TOOL_PROMPT = 'Read notes.txt in the workspace and tell me what it says.';
const TOOL_SCHEMA = [{
  type: 'function',
  function: {
    name: 'read_file',
    description: 'Read a UTF-8 text file from the workspace.',
    parameters: { type: 'object', properties: { path: { type: 'string', description: 'Workspace-relative file path.' } }, required: ['path'] },
  },
}];
const PROFILES = {
  before: { provider: 'baseten' },
  after: { provider: 'modal' },
};

const arguments_ = process.argv.slice(2);
const rounds = Math.max(1, Math.min(10, Number(argument_(['--rounds'])) || DEFAULT_ROUNDS));
const only = String(argument_(['--only']) || '').trim().toLowerCase();
const config = loadConfig();
const secrets = configuredSecrets(config);

function argument_(names) {
  const index = arguments_.findIndex(value => names.includes(value));
  return index >= 0 ? arguments_[index + 1] : undefined;
}

function resolveProfiles() {
  const resolved = [];
  for (const [name, preset] of Object.entries(PROFILES)) {
    if (only && only !== name) continue;
    try {
      const brain = createVoiceBrain({ ...config, voiceModel: '', voiceProvider: preset.provider });
      resolved.push({
        name,
        label: `${name === 'before' ? 'Before' : 'After'} · ${brain.label} · ${brain.model}`,
        model: brain.model,
        baseUrl: brain.client.baseUrl,
        apiKey: brain.client.apiKey,
        requestDefaults: brain.client.requestDefaults,
      });
    } catch (error) {
      console.error(redactText(`${name}: ${error.message}`, { secrets }));
    }
  }
  return resolved;
}

/** Yield complete SSE frames regardless of CRLF or a final unterminated frame. */
async function* frames(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
    let boundary;
    while ((boundary = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      yield frame;
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) yield buffer;
}

function frameData(frame) {
  const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('');
  return !data || data === STREAM_END ? null : data;
}

async function measure(profile, prompt, { tools = false } = {}) {
  const started = performance.now();
  let ttftMs = null;
  let answerMs = null;
  let toolMs = null;
  let reasoningChars = 0;
  let characters = 0;
  let usage = null;
  let toolCalled = false;

  const body = {
    model: profile.model,
    messages: [
      { role: 'system', content: VOICE_REPLY_INSTRUCTIONS },
      { role: 'user', content: prompt },
    ],
    stream: true,
    stream_options: { include_usage: true },
    ...profile.requestDefaults,
    ...(tools ? { tools: TOOL_SCHEMA } : {}),
  };
  const response = await fetch(`${profile.baseUrl}/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(profile.apiKey ? { Authorization: `Bearer ${profile.apiKey}` } : {}),
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  if (!response.ok) {
    const detail = (await response.text()).slice(0, 400);
    throw new Error(`HTTP ${response.status}: ${detail}`);
  }

  for await (const frame of frames(response)) {
    const data = frameData(frame);
    if (!data) continue;
    let chunk;
    try { chunk = JSON.parse(data); } catch { continue; }
    if (chunk.usage) usage = chunk.usage;
    const delta = chunk.choices?.[0]?.delta;
    if (!delta) continue;
    const reasoning = delta.reasoning_content ?? delta.reasoning ?? '';
    if (typeof reasoning === 'string') reasoningChars += reasoning.length;
    if (typeof delta.content === 'string' && delta.content) {
      characters += delta.content.length;
      if (characters === delta.content.length) answerMs = Math.round(performance.now() - started);
    }
    if (Array.isArray(delta.tool_calls) && delta.tool_calls.length) {
      toolCalled = true;
      if (toolMs == null) toolMs = Math.round(performance.now() - started);
    }
    if (ttftMs == null && (reasoning.length || characters || toolCalled)) {
      ttftMs = Math.round(performance.now() - started);
    }
  }
  const totalMs = Math.round(performance.now() - started);
  return {
    ttftMs: ttftMs ?? totalMs,
    answerMs: answerMs ?? totalMs,
    toolMs: toolMs ?? (tools ? totalMs : null),
    totalMs,
    characters,
    reasoningChars,
    toolCalled,
    promptTokens: usage?.prompt_tokens ?? null,
    outputTokens: usage?.completion_tokens ?? null,
  };
}

function percentile(values, fraction) {
  const sorted = [...values].sort((a, b) => a - b);
  if (!sorted.length) return null;
  const index = Math.min(sorted.length - 1, Math.floor(sorted.length * fraction));
  return sorted[index];
}
const median = values => percentile(values, 0.5);

function table(profiles, rows) {
  console.log('\n| Planner | p50 TTFT | p95 TTFT | p50 first answer | p50 total | p50 output tok/s |');
  console.log('| --- | --- | --- | --- | --- | --- |');
  const summary = {};
  for (const profile of profiles) {
    const ok = rows.filter(row => row.profile === profile.name && !row.error);
    const total = ok.map(row => row.totalMs);
    const ttft = ok.map(row => row.ttftMs);
    const tokensPerSecond = ok.filter(row => row.outputTokens && row.totalMs > row.ttftMs)
      .map(row => row.outputTokens / ((row.totalMs - row.ttftMs) / 1000));
    summary[profile.name] = {
      label: profile.label,
      ok: ok.length,
      failed: rows.filter(row => row.profile === profile.name && row.error).length,
      ttftP50: median(ttft), ttftP95: percentile(ttft, 0.95),
      answerP50: median(ok.map(row => row.answerMs)),
      totalP50: median(total), totalP95: percentile(total, 0.95),
      tokensPerSecondP50: median(tokensPerSecond),
      warmupMs: profile.warmupMs ?? null,
      tool: profile.tool ?? null,
    };
    const item = summary[profile.name];
    console.log(`| ${profile.label} | ${item.ttftP50 ?? '—'} ms | ${item.ttftP95 ?? '—'} ms | ${item.answerP50 ?? '—'} ms | ${item.totalP50 ?? '—'} ms | ${item.tokensPerSecondP50 ? item.tokensPerSecondP50.toFixed(1) : '—'} |`);
  }
  return summary;
}

function speedups(summary) {
  const before = summary.before;
  const after = summary.after;
  if (!before?.totalP50 || !after?.totalP50) return;
  const change = (oldValue, newValue) => {
    const percent = ((oldValue - newValue) / oldValue) * 100;
    return `${percent >= 0 ? 'faster' : 'slower'} by ${Math.abs(percent).toFixed(0)}%`;
  };
  console.log(`\nFirst token: Modal is ${change(before.ttftP50, after.ttftP50)} (${before.ttftP50} -> ${after.ttftP50} ms p50).`);
  console.log(`Full reply: Modal is ${change(before.totalP50, after.totalP50)} (${before.totalP50} -> ${after.totalP50} ms p50).`);
  console.log(`First request (cold/warm start): Baseten ${before.warmupMs ?? '—'} ms, Modal ${after.warmupMs ?? '—'} ms.`);
  if (before.tool && after.tool) {
    console.log(`Delegation tool call: Baseten ${before.tool.toolMs} ms (${before.tool.toolCalled ? 'called' : 'no call'}), Modal ${after.tool.toolMs} ms (${after.tool.toolCalled ? 'called' : 'no call'}).`);
  }
}

async function main() {
  const profiles = resolveProfiles();
  if (!profiles.length) {
    console.error('No voice planner could be resolved. Set BASETEN_API_KEY and MODAL_* credentials locally.');
    process.exitCode = 1;
    return;
  }
  const rows = [];
  for (const profile of profiles) {
    console.log(`\nWarming ${profile.label} ...`);
    try {
      const warm = await measure(profile, WARMUP_PROMPT);
      profile.warmupMs = warm.totalMs;
      console.log(`warm-up ${warm.totalMs} ms (${warm.ttftMs} ms to first token)`);
    } catch (error) {
      profile.warmupMs = null;
      console.error(redactText(`${profile.name} warm-up failed: ${error.message}`, { secrets }));
    }
    for (let round = 1; round <= rounds; round++) {
      for (const prompt of PROMPTS) {
        try {
          const result = await measure(profile, prompt);
          const row = { profile: profile.name, round, prompt, ...result };
          rows.push(row);
          console.log(`BENCH_ROW ${JSON.stringify(row)}`);
        } catch (error) {
          const row = { profile: profile.name, round, prompt, error: redactText(error.message, { secrets }) };
          rows.push(row);
          console.error(`BENCH_ROW ${JSON.stringify(row)}`);
        }
      }
    }
    try {
      const tool = await measure(profile, TOOL_PROMPT, { tools: true });
      profile.tool = { toolMs: tool.toolMs, toolCalled: tool.toolCalled, totalMs: tool.totalMs };
      console.log(`tool round trip: ${tool.toolMs} ms, called=${tool.toolCalled}`);
    } catch (error) {
      profile.tool = { toolMs: null, toolCalled: false, error: redactText(error.message, { secrets }) };
      console.error(redactText(`tool check failed: ${error.message}`, { secrets }));
    }
  }
  const summary = table(profiles, rows);
  speedups(summary);
  const failures = rows.filter(row => row.error).length;
  console.log(`\n${rows.length - failures}/${rows.length} requests succeeded across ${profiles.length} planner(s).`);
  if (failures) process.exitCode = 1;
}

await main();
