/** Pure form conversion shared by the renderer and behaviour tests. */
export function channelDraft(preferences) {
  return Object.fromEntries(Object.entries(preferences.manifest.fields).map(([key, field]) => {
    if (field.kind === 'secret') return [key, ''];
    const value = preferences[key] ?? field.default;
    return [key, field.kind === 'bool' ? Boolean(value) : String(value ?? '')];
  }));
}

export function channelPatch(preferences, draft, removed = []) {
  const patch = {};
  for (const [key, field] of Object.entries(preferences.manifest.fields)) {
    if (field.kind === 'secret') {
      if (removed.includes(key)) patch[key] = '';
      else if (String(draft[key] || '').trim()) patch[key] = String(draft[key]).trim();
      continue;
    }
    let value = draft[key];
    if (['int', 'float'].includes(field.kind)) {
      if (String(value).trim() === '' || !Number.isFinite(Number(value))) throw new Error(`Enter a valid ${field.label || key}`);
      value = Number(value);
    } else if (field.source === 'teammates') value = value || null;
    if (value !== preferences[key]) patch[key] = value;
  }
  return patch;
}

export const CHANNEL_FORM_SECTIONS = Object.freeze({ connection: 'Connection', access: 'People and permissions', behaviour: 'Replies', advanced: 'Advanced' });
export const CAPABILITY_LABELS = Object.freeze({ typing: 'Typing indicator', react: 'Reactions', edit: 'Message updates', upload: 'Send files', threads: 'Threads', buttons: 'Approval buttons', voice: 'Spoken replies' });
