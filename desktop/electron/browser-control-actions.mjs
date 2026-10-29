import { CONTROL_ACTIONS, BROWSER_CONNECTION } from '../browser-helper/control-protocol.mjs';

/** Only our desktop IPC caller enters this boundary; changing the grant never closes unrelated browsers. */
export async function runBrowserControlAction({ action, engine, start }) {
  if (!Object.values(CONTROL_ACTIONS).includes(action)) return undefined;
  const service = await start();
  if (action === CONTROL_ACTIONS.status) return service.browserStatus();
  if (action === CONTROL_ACTIONS.setup) {
    await engine.browserPlugins.configureChrome({ connection: BROWSER_CONNECTION });
    await engine.browserPlugins.setEnabled({ mode: 'local', enabled: true });
    return service.setup({ control: true });
  }
  if (action === CONTROL_ACTIONS.revoke) return service.revokeBrowser();
  return service.pauseBrowser(action === CONTROL_ACTIONS.disconnect);
}
