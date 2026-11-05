const FREE_MODEL_SUFFIX = ':free'; // Gateway API identifier convention; pricing metadata is preferred when present.

/** Positive token counts only; malformed provider metadata must not erase the fallback. */
export function declaredContext(model) {
  const candidates = [model.context_length, model.context_window, model.capabilities?.limits?.max_context_window_tokens].map(Number);
  return candidates.find(context => Number.isSafeInteger(context) && context > 0) ?? null;
}

/** Manual tuning wins, then the selected model's catalogue, then the caller's fallback. */
export function modelContextWindow({ client, model, models, contextWindow, contextWindowExplicit = false } = {}) {
  const manual = Number(contextWindow);
  if (contextWindowExplicit && Number.isSafeInteger(manual) && manual > 0) return manual;
  const context = Number(client?.modelCapabilities?.get(model)?.context ?? models?.find(item => item.id === model)?.context);
  return Number.isSafeInteger(context) && context > 0 ? context : contextWindow;
}

export function declaredVision(model) {
  const modalities = model.architecture?.input_modalities || model.input_modalities;
  if (Array.isArray(modalities)) return modalities.includes('image');
  const supports = model.capabilities?.supports;
  return typeof supports?.vision === 'boolean' ? supports.vision : null;
}
export function declaredFree(model) {
  const pricing = model.pricing;
  if (pricing?.prompt != null && pricing?.completion != null) return Number(pricing.prompt) === 0 && Number(pricing.completion) === 0;
  return String(model.id || '').endsWith(FREE_MODEL_SUFFIX);
}
