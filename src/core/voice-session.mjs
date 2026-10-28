import { CompatibleClient, resolveProvider, providerClientOptions, BASETEN_DEFAULT_MODEL, BASETEN_CONTEXT_WINDOW } from './provider.mjs';
import { stripForSpeech } from '../channels/voice.mjs';

// Short spoken receipts, never a claim that delegated work has finished.
const ACK_LINES = {
  'hi-IN': ['Haan.', 'Dekh rahi hoon.', 'Theek hai.'],
  'en-IN': ['Okay.', 'Taking a look.', 'All right.'],
};
const DEFAULT_ACK_LANGUAGE = 'en-IN'; // English backup when detection is absent or unsupported.
const VOICE_REPLY_MAX_SENTENCES = 2; // Complete sentences: the owner's limit for conversational voice replies.
const VOICE_SENTENCE_BOUNDARY = /(?<=[.!?])\s+|(?<=[।॥])\s*/u; // Hindi danda is a sentence ending, including without a space.
const VOICE_SPEAKABLE_CHARACTER = /[\p{L}\p{N}]/u; // Ignore punctuation-only Markdown list markers after speech cleanup.
const VOICE_REPLY_INSTRUCTIONS = `Voice conversation: answer in one or two short sentences, at most two spoken lines. Be crisp and directly answer the request in the user's language.
Skip greetings, repeated questions, lists, recaps and extra offers unless requested. Put any longer details in the requested file or artifact; briefly say where they are.
For work, report the result and any essential failure or permission needed. Never hide a failure or claim an action succeeded without evidence.`;

/** Keep complete sentence boundaries for both speech limits and resumable report clips. */
export function voiceReplySentences(text, { maxChars = Infinity } = {}) {
  return stripForSpeech(text, maxChars).split(VOICE_SENTENCE_BOUNDARY)
    .map(sentence => sentence.trim()).filter(sentence => VOICE_SPEAKABLE_CHARACTER.test(sentence))
    .slice(0, VOICE_REPLY_MAX_SENTENCES);
}
export function voiceReplyForSpeech(text, options) { return voiceReplySentences(text, options).join(' '); }

/** Cache one short clip per sentence in the queue; synthesis begins only when selected. */
export function createVoiceReportSpeech({ jobId, label, text, synthesize, signal, turn, maxChars = Infinity }) {
  const parts = voiceReplySentences(text, { maxChars }).map(text => ({ text, prepare: () => synthesize(text) }));
  return { jobId, label, kind: 'report', text: parts.map(part => part.text).join(' '),
    parts, prepare: parts[0]?.prepare || (async () => null), signal, turn, line: { text: parts.map(part => part.text).join(' ') } };
}

/** One runtime discovery per voice session; unplug/reopen failures force rediscovery. */
export function createVoiceMicrophone({ detect, preferred = '' }) {
  let discovery;
  return {
    get() {
      return discovery ||= Promise.resolve().then(() => detect(preferred)).then(microphone => {
        if (!microphone) discovery = null;
        return microphone;
      }, error => { discovery = null; throw error; });
    },
    invalidate() { discovery = null; },
  };
}

/** Resolve only voice settings; an explicit broken setup must not silently change planners. */
export function createVoiceBrain(config, current = {}) {
  const name = String(config.voiceProvider || '').trim().toLowerCase();
  if (!name) return config.voiceModel ? { client: current.client, model: config.voiceModel, label: 'current provider' } : null;
  const selected = resolveProvider(name);
  if (!selected) throw new Error(`Unknown VOICE_PROVIDER "${name}".`);
  if (selected.name === 'copilot') {
    if (!current.client || resolveProvider(config.provider)?.name !== selected.name) throw new Error('VOICE_PROVIDER=copilot requires the current GitHub Copilot session.');
    return { ...current, model: config.voiceModel || current.model, label: selected.label };
  }
  const apiBase = config.voiceApiBase || (name === 'baseten' && config.basetenBaseUrl) || selected.apiBase;
  const apiKey = selected.apiKey || (selected.keyConfig && config[selected.keyConfig]) || '';
  if (!selected.keyless && !apiKey) throw new Error(`VOICE_PROVIDER=${name} needs ${selected.keyConfig === 'basetenApiKey' ? 'BASETEN_API_KEY' : 'its provider key'}.`);
  const model = config.voiceModel || (name === 'baseten' && config.basetenModel) || selected.defaultModel;
  const contextWindow = config.voiceContextWindow || (config.contextWindowExplicit && config.contextWindow) ||
    (name === 'baseten' && model === BASETEN_DEFAULT_MODEL ? BASETEN_CONTEXT_WINDOW : config.contextWindow);
  return {
    client: new CompatibleClient({ apiBase, apiKey, model, contextWindow, ...providerClientOptions(selected, config) }),
    model,
    contextWindow,
    label: selected.label,
  };
}

/** Pin every model round to the voice planner; restore the typed session even on abort. */
export async function withVoiceBrain(agent, brain, run) {
  const fields = ['client', 'model', 'contextWindow', 'tool', '_activeModelClient', '_activeModel', 'systemSuffix'];
  const saved = fields.map(key => [key, Object.hasOwn(agent, key), agent[key]]);
  agent.systemSuffix = [agent.systemSuffix, VOICE_REPLY_INSTRUCTIONS].filter(Boolean).join('\n\n');
  if (brain) {
    Object.assign(agent, { client: brain.client, model: brain.model, tool: null });
    if (brain.contextWindow) agent.contextWindow = brain.contextWindow;
  }
  try {
    return await run();
  } finally {
    for (const [key, existed, value] of saved) {
      if (existed) agent[key] = value;
      else delete agent[key];
    }
  }
}

/** Synthesize before listening, then select from memory without another network wait. */
export function createAcknowledgements({ synthesize }) {
  const clips = new Map();
  const cursors = new Map();
  let warming;
  return {
    prewarm() {
      return warming ||= Promise.all(Object.entries(ACK_LINES).map(async ([language, lines]) => {
        const results = await Promise.all(lines.map(async text => {
          try {
            const audio = await synthesize(text, language);
            return audio?.length ? { text, audio } : null;
          } catch { return null; }
        }));
        clips.set(language, results.filter(Boolean));
      }));
    },
    next(language) {
      const key = ACK_LINES[language] ? language : DEFAULT_ACK_LANGUAGE;
      const available = clips.get(key) || [];
      if (!available.length) return null;
      const index = cursors.get(key) || 0;
      cursors.set(key, index + 1);
      return available[index % available.length];
    },
  };
}
