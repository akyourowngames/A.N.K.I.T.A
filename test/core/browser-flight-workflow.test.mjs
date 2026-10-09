import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { chromium } from 'playwright';
import { createFlightFixtureServer } from '../../scripts/lib/browser-flight-fixture.mjs';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-flight-workflow-'));
process.env.CONFIG_DIR = path.join(root, 'config');
const { Agent } = await import('../../src/core/agent.mjs');
const { loadSkills } = await import('../../src/core/skills.mjs');
const { BrowserPluginStore, CHROME_MCP_ID, chromeMcpCommand } = await import('../../src/integrations/browser-plugins.mjs');
const { BrowserSessionManager } = await import('../../tools/browser/session.mjs');
const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
const { ChromeBrowserAdapter } = await import('../../tools/browser/chrome.mjs');
const { McpManager } = await import('../../src/integrations/mcp-manager.mjs');
const DEPARTURE_DATE = '2026-10-10'; // Test-only date matching the supplied trace; no production date defaults.
const VIEWPORT = '1280x800'; // CSS pixels: match both native fixture browsers.
const TIMEOUT_MS = 60_000; // Milliseconds for serial native fixture interactions and Chrome startup.
const CLEANUP = { recursive: true, force: true, maxRetries: 10, retryDelay: 100 };
const originalRequest = `Find a one-way flight from Mumbai (BOM) to New Delhi (DEL) on ${DEPARTURE_DATE}.`;
const refFor = (text, label) => {
  const line = text.split('\n').find(line => line.includes('[ref=') && line.replace(/"/g, '').includes(label));
  assert.ok(line, `missing current control: ${label}\n${text}`);
  return line.match(/\[ref=([^\]]+)\]/)[1];
};
const call = (id, name, args) => ({ id, type: 'function', function: { name, arguments: JSON.stringify(args) } });
test.after(async () => {
  assert.equal(fs.realpathSync(path.dirname(root)), fs.realpathSync(os.tmpdir()));
  await fs.promises.rm(root, CLEANUP);
});

for (const mode of ['isolated', 'local']) {
  test(`flight search commits requested direction, date and trip type through real ${mode} refs`, { timeout: TIMEOUT_MS }, async t => {
    const directory = path.join(root, mode); fs.mkdirSync(directory);
    const fixture = await createFlightFixtureServer({ departureDate: DEPARTURE_DATE });
    const mcp = new McpManager();
    const adapter = mode === 'isolated' ? new PlaywrightBrowserAdapter({ profile: path.join(directory, 'profile') }) : new ChromeBrowserAdapter(mcp, {
      ensureConnected: async ctx => {
        const entry = chromeMcpCommand({ connection: 'profile' }).args[0];
        await mcp.connect({ id: CHROME_MCP_ID, command: process.execPath,
          args: [entry, '--no-usage-statistics', '--no-performance-crux', '--headless', `--viewport=${VIEWPORT}`, `--executablePath=${chromium.executablePath()}`, `--user-data-dir=${path.join(directory, 'profile')}`],
          signal: ctx.signal, hidden: true, initTimeoutMs: TIMEOUT_MS, requestTimeoutMs: TIMEOUT_MS });
      },
    });
    const store = new BrowserPluginStore(path.join(directory, 'browser.json')).load(); store.setEnabled(mode, true);
    const manager = new BrowserSessionManager({ store, isolatedFactory: () => adapter, chromeFactory: () => adapter });
    t.after(async () => { await manager.close(); await mcp.closeAll(); await fixture.close(); });
    const skill = loadSkills().find(skill => skill.name === 'browser-use');
    const agent = new Agent({ client: {}, workspacePath: directory, browserManager: manager, skillsEnabled: true,
      config: { tools: true, autoApprove: true, allowPrivateHosts: true, memoryConsolidation: false, model: 'fixture-model', contextWindow: 131072, historyMessages: 8, maxToolSteps: 24 },
      toolContext: { settings: { headless: true } }, print: () => {}, write: () => {} });
    agent.state.activatedTools.add('browser');
    agent.messages.push({ role: 'user', content: originalRequest }, { role: 'assistant', content: 'I can use the browser.' });
    let round = 0;
    const operations = [
      () => ({ action: 'open', url: fixture.url, mode }),
      text => ({ action: 'act', op: 'select', ref: refFor(text, 'Round trip'), text: 'One way' }),
      text => {
        assert.match(text, /native.*select/i, 'custom combobox must return actionable native-select guidance');
        assert.match(text, /click.*option/i); assert.equal(fixture.searches.length, 0);
        return { action: 'act', op: 'click', ref: refFor(text, 'Round trip') };
      },
      text => ({ action: 'act', op: 'click', ref: refFor(text, 'option One way') }),
      text => ({ action: 'act', op: 'click', ref: refFor(text, 'Origin') }),
      text => ({ action: 'fill_form', fields: [{ ref: refFor(text, 'Search origin'), text: 'Mumbai' }] }),
      text => ({ action: 'act', op: 'click', ref: refFor(text, 'option Mumbai (BOM)') }),
      text => { assert.match(text, /Origin.*Mumbai \(BOM\)/); return { action: 'act', op: 'click', ref: refFor(text, 'Destination') }; },
      text => ({ action: 'fill_form', fields: [{ ref: refFor(text, 'Search destination'), text: 'Delhi' }] }),
      text => ({ action: 'act', op: 'click', ref: refFor(text, 'option New Delhi (DEL)') }),
      text => { assert.match(text, /Destination.*New Delhi \(DEL\)/); return { action: 'act', op: 'click', ref: refFor(text, 'Departure') }; },
      text => { assert.match(text, /Snapshot limit reached/); return { action: 'act', op: 'click', ref: refFor(text, '10 October 2026') }; },
      () => ({ action: 'snapshot', query: 'Done' }),
      text => ({ action: 'act', op: 'click', ref: refFor(text, 'button Done') }),
      text => {
        assert.match(text, /Origin.*Mumbai \(BOM\)/); assert.match(text, /Destination.*New Delhi \(DEL\)/);
        assert.match(text, /One way/); assert.match(text, /Departure.*2026-10-10/);
        return { action: 'act', op: 'click', ref: refFor(text, 'Search flights') };
      },
      () => ({ action: 'read' }),
    ];
    agent.streamTurn = async () => {
      assert.ok(agent.messages[0].content.includes(skill.body), 'complete browser skill delivered each round');
      assert.ok(agent.messages.some(message => message.role === 'user' && message.content === originalRequest), 'original itinerary remains after trimming');
      const text = agent.messages.findLast(message => message.role === 'tool')?.content || '';
      if (round < operations.length) return { content: '', toolCalls: [call(`flight-${round}`, 'browser', operations[round++](text))] };
      assert.match(text, /Mumbai \(BOM\).*New Delhi \(DEL\)/);
      assert.match(text, /2026-10-10/); assert.match(text, /One way/);
      return { content: 'Observed the requested flight results; no ticket booked.', toolCalls: [] };
    };
    const reply = await agent.send('use browser');
    assert.match(reply, /no ticket booked/);
    assert.deepEqual(fixture.searches, [{ origin: 'BOM', destination: 'DEL', trip: 'One way', date: DEPARTURE_DATE }]);
    assert.deepEqual(agent.skillAudit.automatic, ['browser-use']);
    console.log(`FLIGHT_WORKFLOW_LIVE mode=${mode} direction=BOM-to-DEL trip=one-way date=${DEPARTURE_DATE} searches=1 calls=${agent.totalToolCalls} skill=true originalRequest=true booking=false`);
  });
}
