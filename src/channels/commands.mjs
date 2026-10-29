export const CHANNEL_COMMAND = '/channels'; // One command name shared with the terminal discovery menu.
export const CHANNEL_ACTIONS = Object.freeze(['list', 'status', 'connect', 'disconnect', 'test', 'doctor', 'pair']);
const CHANNEL_USAGE = '/channels [list|status|connect|disconnect|test|doctor|pair] [channel] [sender-id]';

export async function runChannelCommand(input, { host }) {
  const [action = 'list', id, senderId, ...extra] = String(input || '').trim().split(/\s+/).filter(Boolean);
  if (!CHANNEL_ACTIONS.includes(action) || extra.length || (senderId && action !== 'pair')) throw new Error(`Usage: ${CHANNEL_USAGE}. Keep secrets in Settings or local config, never in a command.`);
  if (['list', 'status'].includes(action)) {
    const view = host.publicView();
    const entries = id ? [[id, view.channels[id]]] : Object.entries(view.channels);
    if (entries.some(([, settings]) => !settings)) throw new Error(`Unknown channel: ${id}`);
    return entries.map(([key, settings]) => `${key}: ${settings.manifest.label} — ${settings.status.running ? `connected${settings.status.account ? ` as ${settings.status.account}` : ''}` : settings.status.error || 'off'}`).join('\n') + '\nKeep this Ankita session open for connected channels.';
  }
  if (action === 'doctor') {
    const report = host.doctor();
    return report.ok ? `Channel settings and delivery ledger OK.${report.rollbackAvailable ? ' A migration backup is available.' : ''}${report.delivery.uncertain ? ` ${report.delivery.uncertain} send(s) have uncertain outcomes; inspect the conversations before retrying.` : ''}` : report.error;
  }
  if (!id) throw new Error(`Usage: ${CHANNEL_USAGE}`);
  const manifest = host.registry.get(id);
  if (action === 'test') {
    const result = await host.verify(id);
    return `${manifest.label}: connected${result.account ? ` as ${result.account}` : ''}.`;
  }
  if (action === 'pair') {
    if (!senderId) throw new Error(`Usage: ${CHANNEL_COMMAND} pair <channel> <sender-id>`);
    const result = host.createPairing(id, senderId);
    return `One-use code for ${senderId}: ${result.code}. They send /pair followed by the code. Expires at ${new Date(result.expiresAt).toLocaleTimeString()}.`;
  }
  if (action === 'connect') {
    const settings = host.store.get(id);
    const missing = manifest.required.filter(key => !settings[key]);
    if (missing.length) throw new Error(`Set ${missing.map(key => manifest.fields[key].env || manifest.fields[key].label || key).join(', ')} in Settings or local config first`);
  }
  const result = await host.save(id, { enabled: action === 'connect' });
  const status = result.channels[id].status;
  if (action === 'disconnect') return `${manifest.label}: disconnected.`;
  return status.running ? `${manifest.label}: connected${status.account ? ` as ${status.account}` : ''}.` : `${manifest.label}: ${status.error || 'saved; connection is not running'}.`;
}
