/** Only bundled descriptors are registered; settings cannot supply import paths. */
export async function loadChannelAdapter(manifest, options = {}) {
  if (!manifest.runtime || !manifest.export) throw new Error(`No transport is installed for ${manifest.label}`);
  const module = await import(new URL(manifest.runtime, import.meta.url));
  const Factory = module[manifest.export];
  if (typeof Factory !== 'function') throw new Error(`The ${manifest.label} transport could not be loaded`);
  return new Factory(options);
}
