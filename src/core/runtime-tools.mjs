import { get } from '../../tools/index.mjs';

const VOICE_CAPABILITY_NAME = /^voice_[a-z][a-z0-9_]*$/u; // Host-only namespace: cannot replace a native tool or impersonate MCP.

export function runtimeVoiceTool(context, name) {
  if (typeof name !== 'string' || !VOICE_CAPABILITY_NAME.test(name) || get(name)) return null;
  const tool = context?.runtimeTools instanceof Map ? context.runtimeTools.get(name) : null;
  return tool?.name === name && typeof tool.run === 'function' && tool.parameters?.type === 'object' ? tool : null;
}

export function runtimeVoiceSpecs(context) {
  if (!(context?.runtimeTools instanceof Map)) return [];
  return [...context.runtimeTools.keys()].flatMap(name => {
    const tool = runtimeVoiceTool(context, name);
    return tool ? [{ type: 'function', function: { name, description: tool.description, parameters: tool.parameters } }] : [];
  });
}

export function runtimeToolFlag(tool, key, args, context) {
  return typeof tool[key] === 'function' ? tool[key](args, context) : tool[key];
}
