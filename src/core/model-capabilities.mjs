const FREE_MODEL_SUFFIX = ':free'; // Gateway API identifier convention; pricing metadata is preferred when present.
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
