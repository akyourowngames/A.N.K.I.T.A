import { Daemon } from '../automation/daemon.mjs';

/** Interactive channel hosting uses the daemon's agent port, without running its schedules. */
export function createCliChannelHost({ store, channelStore, config, client, model, tool, mcp, runPrompt, deliver, adapterFactories = {}, log = () => {} }) {
  const daemon = new Daemon({ store, channelStore, config, client, model, tool, mcp, runPrompt, deliver, channelAdapterFactories: adapterFactories, log });
  return daemon.channelHost;
}
