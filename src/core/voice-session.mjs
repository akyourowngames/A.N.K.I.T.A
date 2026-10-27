import { CompatibleClient, resolveProvider, providerClientOptions, BASETEN_DEFAULT_MODEL, BASETEN_CONTEXT_WINDOW } from './provider.mjs';

// Short spoken receipts, never a claim that delegated work has finished.
const ACK_LINES = {
  'hi-IN': ['Haan.', 'Dekh rahi hoon.', 'Theek hai.'],
  'en-IN': ['Okay.', 'Taking a look.', 'All right.'],
};
const DEFAULT_ACK_LANGUAGE = 'en-IN'; // English backup when detection is absent or unsupported.

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
  if (!brain) return run();
  const fields = ['client', 'model', 'contextWindow', 'tool', '_activeModelClient', '_activeModel'];
  const saved = fields.map(key => [key, Object.hasOwn(agent, key), agent[key]]);
  Object.assign(agent, { client: brain.client, model: brain.model, tool: null });
  if (brain.contextWindow) agent.contextWindow = brain.contextWindow;
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
