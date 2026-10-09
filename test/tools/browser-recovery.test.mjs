import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { chromium } from 'playwright';
import { PlaywrightBrowserAdapter } from '../../tools/browser/playwright.mjs';
import { ChromeBrowserAdapter } from '../../tools/browser/chrome.mjs';
import { BrowserSessionManager } from '../../tools/browser/session.mjs';
import { BrowserPluginStore, CHROME_MCP_ID, chromeMcpCommand } from '../../src/integrations/browser-plugins.mjs';
import { McpManager } from '../../src/integrations/mcp-manager.mjs';
import { browserFields, MAX_BROWSER_FORM_FIELDS, inspectFillControl } from '../../tools/browser/refs.mjs';
import { normalizeBrowserArgs } from '../../tools/browser/pending.mjs';
import { extractPageText, pageTextCaptureOptions } from '../../tools/browser/page-find.mjs';

const CLEANUP = { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }; // Owned Windows test profiles only.
const LIVE_TIMEOUT_MS = 60_000; // Milliseconds: includes one native Chrome bridge startup and all fixture round trips.
const FIELD_COUNT = 6; // A representative form; deliberately below the production batch ceiling.
const AGENT_CONTEXT_BYTES = 128 * 1024; // Bytes: enough to exercise recovery with the complete tool catalogue, without history clipping being the test variable.
const FIXTURE_VIEWPORT = '1280x800'; // CSS pixels: make the long fixture actually exceed Chrome's viewport instead of its default content-sized headless window.
const fixture = '<title>Recovery form</title><body style="min-height:2000px"><form>' + Array.from({ length: FIELD_COUNT }, (_, index) => `<label>Field ${index}<input name="field${index}"></label>`).join('') +
  '<button type="button" onclick="fetch(\'/save\',{method:\'POST\',body:new URLSearchParams(new FormData(this.form)).toString()}).then(()=>document.querySelector(\'main\').textContent=\'Saved form\')">Save form</button></form><main></main>';
const refFor = (text, label) => text.split('\n').find(line => line.includes(label) && line.includes('[ref='))?.match(/\[ref=([^\]]+)\]/)?.[1];
const readingFixture = '<title>Reading fixture</title><main><h1>Travel guide</h1><h2>Fare details</h2><p>A useful paragraph with <a href="/detail">Full details</a>.</p>' +
  '<ul><li>Cabin bag</li><li>Refund rules</li></ul><table><tr><th>Route</th><th>Price</th></tr><tr><td>BOM to DEL</td><td>5900</td></tr></table>' +
  '<p hidden>Hidden fare conditions</p><p style="display:none">Collapsed baggage terms</p><details><summary>More rules</summary><p>Closed disclosure content</p></details>' +
  '<div id="shadow"></div><button style="position:fixed;top:20px;left:20px">Covered booking</button></main>' +
  '<div role="dialog" aria-label="Cookie choices" style="position:fixed;inset:0;background:white"><h2>Cookie choices</h2><button onclick="this.parentElement.remove()">Dismiss overlay</button></div>' +
  '<input type="password" value="PRIVATE_PASSWORD"><input type="hidden" value="PRIVATE_TOKEN"><style>/* STYLE_NOISE */</style>' +
  '<svg><style>/* SVG_STYLE_NOISE */</style><script>/* SVG_SCRIPT_NOISE */</script><text>Graphic caption</text></svg>' +
  '<script>/* SCRIPT_NOISE */document.querySelector("#shadow").attachShadow({mode:"open"}).innerHTML="<p>Shadow reading evidence</p>"</script>';

test('a trailing model token is normalized only for registered browser operations', () => {
  for (const action of ['read', 'find', 'navigate', 'fill_form']) assert.equal(normalizeBrowserArgs({ action: action + '>' }).action, action);
  assert.deepEqual(normalizeBrowserArgs({ action: 'click>', ref: '1-0-0' }), { action: 'act', op: 'click', ref: '1-0-0' });
  assert.equal(normalizeBrowserArgs({ action: 'batch', steps: [{ action: 'read>' }] }).steps[0].action, 'read');
  for (const action of ['delete_file>', 'read>other', '<read>', 'READ>']) assert.equal(normalizeBrowserArgs({ action }).action, action);
});

test('form batch cap rejects oversized work before dispatch', () => {
  const fields = Array.from({ length: MAX_BROWSER_FORM_FIELDS }, (_, index) => ({ ref: `1-0-${index}`, text: 'fixture' }));
  assert.equal(browserFields(fields).length, MAX_BROWSER_FORM_FIELDS);
  assert.throws(() => browserFields([...fields, { ref: '1-0-99', text: 'extra' }]), /fill_form needs/);
  assert.throws(() => browserFields([]), /fill_form needs/);
});

test('malformed action markup is refused with page-control recovery guidance before any browser dispatch', async () => {
  let adaptersCreated = 0;
  const manager = new BrowserSessionManager({ isolatedFactory: () => { adaptersCreated++; throw new Error('must not dispatch'); } });
  const result = await manager.run({ action: 'snapshot<arg_key>query</arg_key><arg_value>Done' });
  assert.match(result, /^Error: Unknown browser action:/);
  assert.match(result, /action.*snapshot.*query.*separate/i);
  assert.match(result, /native JSON/i);
  assert.match(result, /not.*files/i);
  assert.equal(adaptersCreated, 0);
  await manager.close();
});

for (const mode of ['isolated', 'local']) {
  test(`real ${mode} browser batches edits and recovers current refs without replay`, { timeout: LIVE_TIMEOUT_MS }, async t => {
    assert.ok(fs.existsSync(chromium.executablePath()), 'Live recovery gate requires installed Chromium');
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), `ankita-recovery-${mode}-`));
    const saves = [];
    const server = http.createServer((request, response) => {
      if (request.method === 'POST') {
        let body = '';
        request.on('data', chunk => { body += chunk; });
        request.on('end', () => { saves.push(Object.fromEntries(new URLSearchParams(body))); response.end('saved'); });
      } else { response.setHeader('content-type', 'text/html'); response.end(request.url === '/reading' ? readingFixture : fixture); }
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const url = `http://127.0.0.1:${server.address().port}/`;
    const mcp = new McpManager(), calls = [], dispatches = [];
    const nativeCall = mcp.callTool.bind(mcp);
    mcp.callTool = async (name, args, options) => { const call = { name, args }; calls.push(call); const result = await nativeCall(name, args, options); call.result = result; return result; };
    const adapter = mode === 'isolated' ? new PlaywrightBrowserAdapter({ profile: path.join(directory, 'profile') }) : new ChromeBrowserAdapter(mcp, {
      ensureConnected: async ctx => {
        const entry = chromeMcpCommand({ connection: 'profile' }).args[0];
        await mcp.connect({ id: CHROME_MCP_ID, command: process.execPath,
          args: [entry, '--no-usage-statistics', '--no-performance-crux', '--headless', `--viewport=${FIXTURE_VIEWPORT}`, `--executablePath=${chromium.executablePath()}`, `--user-data-dir=${path.join(directory, 'profile')}`],
          signal: ctx.signal, hidden: true, initTimeoutMs: 25_000, requestTimeoutMs: 15_000 });
      },
    });
    const store = new BrowserPluginStore(path.join(directory, 'browser.json')).load(); store.setEnabled(mode, true);
    const manager = new BrowserSessionManager({ store, isolatedFactory: () => adapter, chromeFactory: () => adapter });
    const ctx = { cwd: directory, settings: { headless: true }, config: { allowPrivateHosts: true, browserRuntimeV2: true }, onBrowserDispatch: event => dispatches.push(event) };
    t.after(async () => {
      await manager.close(); await mcp.closeAll(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
      assert.equal(fs.realpathSync(path.dirname(directory)), fs.realpathSync(os.tmpdir())); await fs.promises.rm(directory, CLEANUP);
    });
    let snapshot = await manager.run({ action: 'open', mode, url }, ctx);

    await t.test('automatic tab selects the current page without invalidating its refs', async () => {
      const output = await manager.run({ action: 'act', mode, tab: 'auto', op: 'fill', ref: refFor(snapshot, 'Field 0'), text: 'automatic' }, ctx);
      assert.match(output, /fill complete/, output);
      snapshot = output;
    });

    await t.test('six fields take one facade call and Chrome uses one native form mutation', async () => {
      snapshot = await manager.run({ action: 'snapshot', mode }, ctx);
      const before = calls.length;
      const fields = Array.from({ length: FIELD_COUNT }, (_, index) => ({ ref: refFor(snapshot, `Field ${index}`), text: `value-${index}` }));
      const output = await manager.run({ action: 'fill_form', mode, fields }, ctx);
      assert.match(output, /Filled 6 fields/, output);
      if (mode === 'local') {
        const issued = calls.slice(before);
        assert.equal(issued.filter(call => call.name.endsWith('__fill_form')).length, 1);
        assert.equal(issued.filter(call => call.name.endsWith('__type_text') || call.name.endsWith('__take_snapshot')).length, 0);
      }
      const saved = await manager.run({ action: 'act', mode, op: 'click', ref: refFor(output, 'Save form') }, ctx);
      assert.match(saved, /click complete/);
      assert.match(await manager.run({ action: 'find>', mode, query: 'Saved form' }, ctx), /Saved form/);
      assert.equal(saves.length, 1);
      assert.deepEqual(saves[0], Object.fromEntries(fields.map((field, index) => [`field${index}`, field.text])));
      snapshot = saved;
    });

    await t.test('stale refs are genuine failed receipts with usable recovery refs and zero writes', async () => {
      const stale = refFor(snapshot, 'Field 0');
      await manager.run({ action: 'snapshot', mode }, ctx);
      dispatches.length = 0;
      const result = await adapter.execute({ action: 'act', op: 'fill', ref: stale, text: 'must-not-write' }, ctx);
      assert.equal(result.status, 'failed', JSON.stringify(result));
      assert.equal(result.steps[0].retrySafe, true);
      assert.match(result.error.message, /Fresh snapshot:/);
      assert.ok(result.observation.controls.length);
      assert.equal(dispatches.filter(event => event.phase === 'start').length, 0);
      const ref = result.observation.controls.find(control => control.name.includes('Field 0')).ref;
      const recovered = await adapter.execute({ action: 'act', op: 'fill', ref, text: 'recovered' }, ctx);
      assert.equal(recovered.status, 'executed');
      assert.equal(saves.length, 1);
    });

    if (mode === 'isolated') await t.test('a first field replaced after preflight remains a zero-dispatch recoverable failure', async () => {
      snapshot = await adapter.run({ action: 'snapshot' }, ctx);
      const fieldRef = refFor(snapshot, 'Field 0');
      const frame = adapter.page.mainFrame(), nativeLocator = frame.locator;
      let replaced = false;
      frame.locator = function (...args) {
        const locator = nativeLocator.apply(this, args), nativeEvaluate = locator.evaluate;
        locator.evaluate = async function (fn, ...parameters) {
          const value = await nativeEvaluate.call(this, fn, ...parameters);
          if (fn === inspectFillControl && !replaced) {
            replaced = true;
            await adapter.page.evaluate(() => { const input = document.querySelector('input'); input.replaceWith(input.cloneNode(true)); });
          }
          return value;
        };
        return locator;
      };
      dispatches.length = 0;
      let result;
      try { result = await adapter.execute({ action: 'fill_form', fields: [{ ref: fieldRef, text: 'must-not-dispatch' }] }, ctx); }
      finally { frame.locator = nativeLocator; }
      assert.ok(replaced, 'actual native DOM replacement occurred after metadata validation');
      assert.equal(result.status, 'failed'); assert.equal(result.steps[0].retrySafe, true);
      assert.equal(dispatches.filter(event => event.phase === 'start').length, 0);
      assert.match(result.error.message, /Fresh snapshot:/);
      assert.doesNotMatch(result.error.message, /Earlier fields may|Form filling stopped/);
      assert.notEqual(await adapter.page.locator('input').first().inputValue(), 'must-not-dispatch');
      const fresh = result.observation.controls.find(control => control.name.includes('Field 0')).ref;
      const recovered = await adapter.execute({ action: 'fill_form', fields: [{ ref: fresh, text: 'race recovered' }] }, ctx);
      assert.equal(recovered.status, 'executed');
      assert.equal(await adapter.page.locator('input').first().inputValue(), 'race recovered');
    });

    await t.test('scroll reaches below the fold and returns current controls', async () => {
      snapshot = await manager.run({ action: 'snapshot', mode }, ctx);
      const output = await manager.run({ action: 'act', mode, op: 'scroll', ref: refFor(snapshot, 'Field 0'), text: '600' }, ctx);
      assert.match(output, /scroll complete/, output);
      if (mode === 'isolated') await adapter.page.waitForFunction(() => scrollY > 0);
      else {
        const position = await mcp.callTool(`mcp__${CHROME_MCP_ID}__evaluate_script`, { pageId: adapter.pageId, function: '() => window.scrollY' });
        const metrics = await mcp.callTool(`mcp__${CHROME_MCP_ID}__evaluate_script`, { pageId: adapter.pageId,
          function: '() => ({ top:scrollY, innerH:innerHeight, root:document.scrollingElement.tagName, nodes:[...document.querySelectorAll("input,form,body,html")].map(node=>({tag:node.tagName,h:node.scrollHeight,c:node.clientHeight,top:node.scrollTop,overflow:getComputedStyle(node).overflowY})) })' });
        assert.match(position, /```json\s*[1-9]\d*\s*```/, metrics + '\n' + calls.findLast(call => call.args.function?.includes('scrollBrowserControl'))?.result);
      }
      assert.ok(refFor(output, 'Save form'), 'scroll publishes the next actionable refs');
    });

    for (const browserRuntimeV2 of [false, true]) {
      await t.test(`agent recovers a stale batch across rounds and submits once (runtimeV2=${browserRuntimeV2})`, async () => {
        const { Agent } = await import('../../src/core/agent.mjs');
        const call = (id, args) => ({ id, type: 'function', function: { name: 'browser', arguments: JSON.stringify(args) } });
        const agent = new Agent({ client: {}, config: { ...ctx.config, browserRuntimeV2, tools: true, autoApprove: true,
          contextWindow: AGENT_CONTEXT_BYTES, historyMessages: 40, maxTokens: 1000, maxToolSteps: 12, memoryRecallChars: 0, memoryConsolidation: false },
          workspacePath: directory, browserManager: manager });
        const before = saves.length;
        let round = 0, staleFields;
        const actions = [];
        agent.streamTurn = async () => {
          round++;
          const output = agent.messages.findLast(message => message.role === 'tool')?.content || '';
          const next = args => { actions.push(args.action); return { content: '', toolCalls: [call(`recovery-${round}`, { mode, ...args })] }; };
          if (round === 1) return { content: '', toolCalls: [{ id: 'discover', type: 'function', function: { name: 'find_tools', arguments: JSON.stringify({ query: 'browser' }) } }] };
          if (round === 2) return next({ action: 'open', url });
          if (round === 3) {
            staleFields = Array.from({ length: FIELD_COUNT }, (_, index) => ({ ref: refFor(output, `Field ${index}`), text: `agent-${index}` }));
            return next({ action: 'snapshot' });
          }
          if (round === 4) return next({ action: 'fill_form', fields: staleFields });
          if (round === 5) {
            assert.match(output, /Error:.*Stale ref/);
            assert.match(output, /Fresh snapshot:/);
            assert.equal(saves.length, before);
            return next({ action: 'fill_form', fields: staleFields.map((field, index) => ({ ...field, ref: refFor(output, `Field ${index}`) })) });
          }
          if (round === 6) { assert.match(output, /Filled 6 fields/); return next({ action: 'act', op: 'click', ref: refFor(output, 'Save form') }); }
          if (round === 7) {
            // The zero-latency scripted provider must not outrun the fixture's asynchronous fetch/render callback.
            if (mode === 'isolated') await adapter.page.getByText('Saved form', { exact: true }).waitFor({ timeout: LIVE_TIMEOUT_MS });
            return next({ action: 'find', query: 'Saved form' });
          }
          assert.match(output, /Saved form/);
          return { content: 'Saved the six fields once.', toolCalls: [] };
        };
        assert.equal(await agent.send('Fill all six fixture fields together, then save once.'), 'Saved the six fields once.');
        assert.equal(round, 8);
        assert.equal(saves.length, before + 1);
        assert.deepEqual(saves.at(-1), Object.fromEntries(staleFields.map((field, index) => [`field${index}`, field.text])));
        for (const message of agent.messages.filter(message => message.tool_calls)) for (const declared of message.tool_calls) {
          assert.equal(agent.messages.filter(reply => reply.tool_call_id === declared.id).length, 1);
        }
        console.log('AGENT_REF_RECOVERY_LIVE', JSON.stringify({ mode, browserRuntimeV2, rounds: round, writes: saves.length - before, actions }));
      });
    }
    await t.test('Markdown reads preserve structure, open shadows and optional hidden evidence without exposing secrets', async () => {
      const opened = await manager.run({ action: 'open', mode, url: new URL('/reading', url).href }, ctx);
      assert.match(opened, /^\s*- \[ref=[^\]]+\].*Dismiss overlay/m);
      const covered = adapter.observation.controls.find(control => control.name === 'Covered booking');
      assert.equal(covered?.states.covered, true);
      assert.equal(covered?.actionable, false);
      assert.ok(refFor(opened, 'More rules'), 'a closed disclosure must have a real observed interaction ref');
      const normal = await manager.run({ action: 'read', mode }, ctx);
      assert.match(normal, /^# Travel guide/m);
      assert.match(normal, /^## Fare details/m);
      assert.match(normal, /\[Full details\]\(http[^)]+\/detail\)/);
      assert.match(normal, /- Cabin bag/);
      assert.match(normal, /\| Route \| Price \|/);
      assert.match(normal, /Shadow reading evidence/);
      assert.doesNotMatch(normal, /Hidden fare conditions|Collapsed baggage terms|Closed disclosure content/);
      const all = await manager.run({ action: 'read', mode, filter: 'all' }, ctx);
      assert.match(all, /\[hidden DOM\].*Hidden fare conditions/);
      assert.match(all, /Collapsed baggage terms/);
      assert.match(all, /Closed disclosure content/);
      assert.doesNotMatch(all, /PRIVATE|NOISE/, 'exclusion must hold even when Markdown escapes underscores in a sentinel');
      assert.equal(adapter.observation.controls.length, 0, 'read evidence does not mint actionable refs for hidden content');
      const found = await manager.run({ action: 'find', mode, query: 'Hidden fare conditions', filter: 'all' }, ctx);
      assert.match(found, /Hidden fare conditions/);
      assert.match(found, /not action refs/i);
      const dismissed = await manager.run({ action: 'act', mode, op: 'click', ref: refFor(opened, 'Dismiss overlay') }, ctx);
      assert.match(dismissed, /click complete/);
      assert.equal(adapter.observation.controls.find(control => control.name === 'Covered booking')?.states.covered, false);
      const expanded = await manager.run({ action: 'act', mode, op: 'click', ref: refFor(dismissed, 'More rules') }, ctx);
      assert.match(expanded, /click complete/);
      assert.match(await manager.run({ action: 'read', mode }, ctx), /Closed disclosure content/);
      if (mode === 'isolated') {
        const CAPTURE_CHARACTERS = 32; // Small test-only budget: prove source omissions rather than silently clipping evidence.
        const clipped = await adapter.page.evaluate(extractPageText, pageTextCaptureOptions({ action: 'read' }, CAPTURE_CHARACTERS));
        assert.equal(clipped.truncated, true); assert.ok(clipped.text.length <= CAPTURE_CHARACTERS);
        const bounded = await adapter.page.evaluate(extractPageText, { ...pageTextCaptureOptions({ action: 'read' }), nodes: 2 });
        assert.equal(bounded.truncated, true); assert.equal(bounded.text, '');
      }
      console.log('MARKDOWN_PAGE_READING_LIVE', JSON.stringify({ mode, markdown: true, hidden: true, covered: true, shadow: true, secretLeaks: false, writes: saves.length }));
    });
    console.log('BROWSER_RECOVERY_LIVE', JSON.stringify({ mode, fields: FIELD_COUNT, writes: saves.length, nativeFormCalls: calls.filter(call => call.name.endsWith('__fill_form')).length }));
  });
}

test('real Playwright never retargets a replaced or cloned control by label', { timeout: LIVE_TIMEOUT_MS }, async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-ref-identity-'));
  const server = http.createServer((_request, response) => { response.setHeader('content-type', 'text/html'); response.end('<label>Account<input></label><button onclick="document.querySelector(\'main\').textContent=\'wrong\'">Confirm</button><main></main>'); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(directory, 'profile') });
  const ctx = { config: { allowPrivateHosts: true, browserRuntimeV2: true }, settings: { headless: true } };
  t.after(async () => { await adapter.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); assert.equal(fs.realpathSync(path.dirname(directory)), fs.realpathSync(os.tmpdir())); await fs.promises.rm(directory, CLEANUP); });
  const url = `http://127.0.0.1:${server.address().port}/`;
  for (const clone of [false, true]) {
    await t.test(clone ? 'copied ref attributes do not transfer node identity' : 'a same-named replacement does not inherit the old ref', async () => {
      const opened = await adapter.execute({ action: 'open', url }, ctx);
      const ref = opened.observation.controls.find(control => control.name === 'Confirm').ref;
      await adapter.page.locator('button').evaluate((node, clone) => {
        const replacement = clone ? node.cloneNode(true) : document.createElement('button');
        replacement.textContent = 'Confirm'; replacement.onclick = () => { document.querySelector('main').textContent = 'wrong'; }; node.replaceWith(replacement);
      }, clone);
      const attempted = await adapter.execute({ action: 'act', op: 'click', ref }, ctx);
      assert.equal(attempted.status, 'failed', JSON.stringify(attempted));
      assert.equal(await adapter.page.locator('main').innerText(), '');
      const fresh = attempted.observation.controls.find(control => control.name === 'Confirm').ref;
      assert.equal((await adapter.execute({ action: 'act', op: 'click', ref: fresh }, ctx)).status, 'executed');
      assert.equal(await adapter.page.locator('main').innerText(), 'wrong');
    });
  }
  console.log('REF_IDENTITY_LIVE: checked same-label replacement, copied DOM ref, and fresh-ref completion');
});
