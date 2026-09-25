import { CompatibleClient, resolveProvider, pickModel } from './provider.mjs';
import { CopilotClient, resolveGithubToken, deviceLogin, writeAuth } from './auth.mjs';

/** Shared provider bootstrap for terminal and desktop front ends. */
export async function createSession({
  config,
  onDeviceCode,
  CopilotClientClass = CopilotClient,
  CompatibleClientClass = CompatibleClient,
  resolveToken = resolveGithubToken,
  login = deviceLogin,
} = {}) {
  const provider = config.provider === 'custom'
    ? { name: 'custom', label: 'Custom provider', apiBase: config.apiBase, apiKey: config.apiKey, defaultModel: '', keyless: !config.apiKey }
    : resolveProvider(config.provider);
  if (!provider) throw new Error(`Unknown provider "${config.provider}"`);
  if (provider.name === 'custom' && !config.apiBase) throw new Error('Custom provider API URL is required');
  if (provider.name !== 'copilot' && !config.apiBase) {
    config.apiBase = provider.apiBase;
    config.apiKey ||= provider.apiKey || (provider.keyConfig && config[provider.keyConfig]) || '';
    config.model ||= provider.defaultModel || '';
  }

  let client;
  if (config.apiBase) {
    client = new CompatibleClientClass({ apiBase: config.apiBase, apiKey: config.apiKey, model: config.model, contextWindow: config.contextWindow });
  } else {
    let token = resolveToken();
    if (!token) {
      token = await login(onDeviceCode ? { onDeviceCode, log: () => {}, write: () => {} } : {});
      writeAuth({ github_token: token, saved_at: new Date().toISOString() });
    }
    client = new CopilotClientClass(token);
    await client.ensureToken();
  }

  let tool = null;
  if (config.toolProvider || config.toolModel) {
    const selected = resolveProvider(config.toolProvider || config.provider);
    if (!selected) throw new Error(`Unknown tool provider "${config.toolProvider}"`);
    const model = config.toolModel || selected.defaultModel || config.model;
    const base = config.toolApiBase || selected.apiBase;
    if (base) {
      const key = config.toolApiKey || selected.apiKey || (selected.keyConfig && config[selected.keyConfig]) || '';
      tool = { client: new CompatibleClientClass({ apiBase: base, apiKey: key, model, contextWindow: config.contextWindow }), model };
    } else if (client instanceof CopilotClientClass) {
      tool = { client, model };
    } else {
      const token = resolveToken();
      if (!token) throw new Error('The tool model needs a GitHub login');
      const toolClient = new CopilotClientClass(token);
      await toolClient.ensureToken();
      tool = { client: toolClient, model };
    }
  }

  const models = await client.models();
  const picked = pickModel(models, config.model, config.tools);
  if (!config.contextWindowExplicit && picked.context) config.contextWindow = picked.context;
  return { client, tool, models, model: picked.id, provider, picked };
}
