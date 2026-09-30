import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { fork } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { complexLoginFixture, LOGIN_USER, LOGIN_PASSWORD } from './fixtures/complex-login.mjs';

const CHILD_FLAG = '--isolated-worker'; // Child isolates memory/state without writing provider credentials.
const HOST = '127.0.0.1', DEFAULT_EXECUTION_MS = 240_000, TOKEN_LIMIT = 600_000; // Test budget covers cumulative prompt tokens across two complex runs.
const EXECUTION_OPTION = '--timeout-ms'; // Explicit verifier deadline override for slow providers; milliseconds.
const executionIndex = process.argv.indexOf(EXECUTION_OPTION);
const EXECUTION_MS = executionIndex >= 0 ? Number(process.argv[executionIndex + 1]) : DEFAULT_EXECUTION_MS;
assert.ok(Number.isFinite(EXECUTION_MS) && EXECUTION_MS > 0, 'Verification deadline must be positive milliseconds');
const VALUE = 'Live provider verification'; // Synthetic text submitted only to this local fixture.
const VERIFICATION_DEADLINE_MS = EXECUTION_MS * 4; // Creation, expired-session runs, MFA and baseline run.
if (!process.argv.includes(CHILD_FLAG)) {
  const { CONFIG_DIR, loadConfig } = await import('../src/core/config.mjs');
  const { DesktopSettingsStore, applyDesktopSettings } = await import('../desktop/electron/settings.mjs');
  const config = applyDesktopSettings(loadConfig(), new DesktopSettingsStore(path.join(CONFIG_DIR, 'desktop-settings.json')).load().data);
  const modelIndex = process.argv.indexOf('--model');
  if (modelIndex >= 0) config.model = process.argv[modelIndex + 1]; // Explicit verifier selection; never changes user settings.
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-job-provider-'));
  try {
    const child = fork(fileURLToPath(import.meta.url), [CHILD_FLAG, ...process.argv.slice(2)], { env: { ...process.env, CONFIG_DIR: directory }, stdio: ['ignore', 'inherit', 'inherit', 'ipc'] });
    const completed = new Promise((resolve, reject) => { child.once('error', reject); child.once('exit', code => code === 0 ? resolve() : reject(new Error(`Live provider verifier exited ${code}`))); });
    child.send(config); await completed;
  } finally {
    if (process.argv.includes('--keep-artifacts')) console.log(`LIVE_PROVIDER_ARTIFACTS: ${directory}`);
    else {
      assert.equal(path.dirname(fs.realpathSync(directory)), fs.realpathSync(os.tmpdir()), 'Cleanup stays inside the temporary directory');
      fs.rmSync(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
    }
  }
} else {
  const config = await new Promise(resolve => process.once('message', resolve)); process.disconnect();
  const [{ CONFIG_DIR }, { createSession }, { Agent }, { DesktopScheduler }, { ApprovalRegistry }, { BrowserSessionManager }, { BrowserPluginStore }] = await Promise.all([
    import('../src/core/config.mjs'), import('../src/core/bootstrap.mjs'), import('../src/core/agent.mjs'),
    import('../desktop/electron/scheduler.mjs'), import('../desktop/electron/approvals.mjs'),
    import('../tools/browser/session.mjs'), import('../src/integrations/browser-plugins.mjs'),
  ]);
  Object.assign(config, { tools: true, desktopBackgroundJobs: true, allowPrivateHosts: true, memoryRecallChars: 0, memoryConsolidation: false, maxToolSteps: 24, maxToolCalls: 32, systemExtra: '' });
  const posts = [], receipts = [], steps = [];
  const server = http.createServer((request, response) => {
    const url = new URL(request.url, `http://${HOST}`); response.setHeader('content-type', 'text/html');
    if (url.pathname === '/publish') { posts.push(url.searchParams.get('message')); response.end(`<title>Confirmed</title><main>Published: ${VALUE}</main>`); }
    else response.end('<title>Live verification form</title><form action="/publish"><label>Message<input name="message"></label><button>Publish</button></form>');
  });
  let scheduler, manager, complex;
  const watchdog = setTimeout(() => { console.error('LIVE_PROVIDER_DEADLINE: no automatic retry'); process.exitCode = 1; void scheduler?.stop(); server.closeAllConnections(); }, VERIFICATION_DEADLINE_MS);
  try {
    await new Promise(resolve => server.listen(0, HOST, resolve));
    const base = `http://${HOST}:${server.address().port}`;
    const session = await createSession({ config, login: async () => { throw new Error('Provider requires login; verifier will not start a login flow'); } });
    const owner = { id: 'live-verifier', name: 'Verification', persona: '', model: session.model };
    const store = new BrowserPluginStore(path.join(CONFIG_DIR, 'browser-plugins.json')).load(); store.setEnabled('isolated', true);
    complex = await complexLoginFixture();
    const { BrowserCredentials } = await import('../desktop/electron/browser-credentials.mjs');
    manager = new BrowserSessionManager({ store, credentials: new BrowserCredentials({ store: { withCredentials: async ({ website }, callback) => website === complex.base ? callback({ username: LOGIN_USER, password: LOGIN_PASSWORD }) : null }, requests: { request: () => assert.fail('background password dialog') }, emit: () => {} }) });
    class VerifiedAgent extends Agent {
      constructor(options) {
        const original = options.toolContext.onBrowserError;
        options.toolContext.onBrowserError = error => { console.error(`LIVE_BROWSER_ERROR: ${error.name}: ${error.message}`); original(error); };
        super(options);
      }
      async runToolCall(call, args) {
        const result = await super.runToolCall(call, args);
        if (call.function.name === 'browser') {
          let input = args || {}; try { input = args || JSON.parse(call.function.arguments); } catch {}
          console.log(`LIVE_BROWSER_CALL: ${JSON.stringify({ action: input.action, mode: input.mode, ...(input.action === 'login' ? { hasWebsite: Boolean(input.website || input.url), fields: input.credential_fields?.map(field => field.credential), hasSubmit: Boolean(input.submit_ref) } : {}) })}`);
          if (/^Error/i.test(String(result))) console.error(`LIVE_BROWSER_RESULT: ${String(result).split('\n')[0]}`);
        }
        return result;
      }
    }
    const engine = { config, client: session.client, tool: session.tool, model: session.model, AgentClass: VerifiedAgent, browserManager: manager, turns: new Map(),
      teammates: { list: () => [owner], find: id => id === owner.id ? owner : null },
      approvals: new ApprovalRegistry(() => {}), deliverRoutine: async receipt => { receipts.push(receipt); return true; },
      emit: event => { if (event.type === 'routine-run-step') { steps.push(event.detail); console.log(`LIVE_PROVIDER_STEP: ${event.step} ${event.detail}`); } else if (event.type === 'scheduler-error') console.error(`LIVE_BROWSER_ERROR: ${event.message}`); },
    };
    scheduler = new DesktopScheduler({ engine, file: path.join(CONFIG_DIR, 'state.json'), sessionsDir: CONFIG_DIR });
    const creator = new Agent({ client: session.client, tool: session.tool, config, allowedTools: new Set(['find_tools', 'browser', 'schedule', 'schedule_status', 'recall', 'remember', 'project_memory']), browserManager: manager, browserThreadId: owner.id, confirm: async () => true, skillsEnabled: false,
      toolContext: { scheduler, scheduleThreadId: owner.id, authorizeNavigation: async url => { assert.ok([base, complex.base].includes(new URL(url).origin), 'Verification only browses its local fixtures'); return true; } }, print: () => {}, write: () => {} });
    creator.browserCredentialAllowed = true;
    creator.model = session.model;
    const task = `Open ${complex.base}/dashboard. Use browser login for BOTH the username and password using the saved account and observed refs. Never invent an account or type guessed credentials. The sign-in is username-first, then a same-origin password iframe with a hidden CSRF field. After sign-in, publish exactly ${JSON.stringify(VALUE)} once using Report text and Publish report, then read the confirmation. Never guess refs, pass passwords or repeat a submission.`;
    console.log(`LIVE_CREATOR_READY: model=${session.model}; tools=${creator.currentSpecs().map(spec => spec.function.name).join(',')}`);
    const creationReply = await creator.send(`Only define a recurring job; do not open, inspect or interact with the website during this turn. Create an active scheduled task named Complex scheduled sign-in, daily 09:00, with enabled=true, for this task: ${task}. Write clear standalone instructions and observed success criteria for the scheduled worker. Keep it enabled for future scheduled fires; do not call action run now or invent execution limits.`, { onToolCall: call => {
      let args = {}; try { args = JSON.parse(call.function.arguments); } catch {}
      console.log(`LIVE_SCHEDULE_TOOL: ${call.function.name}; ${JSON.stringify({ action: args.action, cron: args.cron, enabled: args.enabled, browserPolicy: args.browserPolicy })}`);
    } });
    const scheduled = scheduler.list(); assert.equal(scheduled.length, 1, `Model did not create the job: ${creationReply}`); assert.equal(scheduled[0].enabled, true); assert.equal(scheduled[0].browserPolicy, 'autonomous');
    assert.equal(scheduled[0].executionPolicy, 'complete');
    assert.ok(scheduled[0].prompt.includes(complex.base), 'The model-written instructions retain the target resource');
    assert.ok(scheduled[0].prompt.includes(VALUE), 'The model-written instructions retain the exact requested submission');
    fs.writeFileSync(path.join(CONFIG_DIR, 'model-written-job-prompt.txt'), scheduled[0].prompt); // Only local fixture instructions, never provider credentials.
    assert.equal(complex.audit.posts.length, 0, 'Defining a schedule must not publish the report');
    const updateReply = await creator.send('Update the task you just created to weekdays 10:30. Keep its task instructions and identity. Do not run it now.', { onToolCall: call => {
      let args = {}; try { args = JSON.parse(call.function.arguments); } catch {}
      console.log(`LIVE_UPDATE_TOOL: ${call.function.name}; ${JSON.stringify({ action: args.action, id: args.id, cron: args.cron, patch: args.patch && { fields: Object.keys(args.patch), cron: args.patch.cron } })}`);
    } });
    assert.equal(scheduler.list().length, 1); assert.equal(scheduler.list()[0].cron, '30 10 * * 1-5', `Model did not update the job: ${updateReply}`);
    console.log('LIVE_MODEL_SCHEDULING_OK: one active autonomous job; update retained its identity; no manual form');
    for (let attempt = 0; attempt < 2; attempt++) {
      complex.expire();
      await scheduler.runNow(scheduled[0].id); await scheduler.daemon.drain(EXECUTION_MS);
      const receipt = receipts.at(-1);
      console.log(`LIVE_JOB_RECEIPT: ${receipt?.status}; ${receipt?.text}`);
      assert.equal(receipt?.status, 'ok', `Complex job status: ${receipt?.status}; ${receipt?.text}`);
      assert.equal(complex.audit.posts.length, attempt + 1); assert.ok(receipt.proof?.screenshot);
    }
    assert.equal(complex.audit.passwords, 2); assert.equal(complex.audit.wrongCredentials, 0); assert.equal(complex.audit.leakedQueries, 0);
    console.log(`LIVE_COMPLEX_LOGIN_OK: real model; username-first; password iframe; CSRF; expired session; posts=${complex.audit.posts.length}; passwordSubmits=${complex.audit.passwords}; leaks=0`);
    const mfaJob = scheduler.add({ name: 'MFA boundary', cron: '@daily', threadId: owner.id, browserPolicy: 'autonomous', timeoutMs: EXECUTION_MS, budget: { maxTokensPerDay: TOKEN_LIMIT }, prompt: `Open ${complex.base}/mfa and sign in using saved browser credentials and observed refs. If a fresh verification code is required, call schedule with action needs_input and explain the missing code, then stop. Never guess a code.` });
    await scheduler.runNow(mfaJob.id); await scheduler.daemon.drain(EXECUTION_MS);
    assert.equal(receipts.at(-1)?.status, 'skipped-needs-foreground'); assert.equal(complex.audit.mfa, 1); assert.equal(complex.audit.posts.length, 2);
    console.log('LIVE_MFA_BOUNDARY_OK: model requested foreground verification; no guessed code or additional submission');
    const routine = scheduler.add({ name: 'Live model browser verification', cron: 'daily 09:00', threadId: owner.id, timeoutMs: EXECUTION_MS,
      allow: { mode: 'isolated', read: true, interact: true, login: false, sites: [`${base}/*`] }, onNewRequest: 'deny', budget: { maxTokensPerDay: TOKEN_LIMIT },
      prompt: `Use the browser to open ${base}/form, fill Message with exactly ${JSON.stringify(VALUE)}, click Publish once, read the confirmation, and report whether the exact text was published. This is a disposable local test.`,
    });
    await scheduler.runNow(routine.id); await scheduler.daemon.drain(EXECUTION_MS);
    assert.equal(receipts.at(-1)?.status, 'ok', `Job status: ${receipts.at(-1)?.status}; ${receipts.at(-1)?.text}`);
    assert.deepEqual(posts, [VALUE], 'Exactly one submission with the requested text');
    assert.ok(steps.length >= 3); assert.ok(receipts.at(-1).proof?.screenshot);
    console.log(`LIVE_PROVIDER_JOB_OK: provider=${session.provider.name}; model=${session.model}; browserSteps=${steps.length}; posts=${posts.length}; screenshot=true`);
  } finally { clearTimeout(watchdog); await scheduler?.stop(); await manager?.close(); await complex?.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
}
