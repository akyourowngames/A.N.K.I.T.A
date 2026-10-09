import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createFlightFixtureServer } from './lib/browser-flight-fixture.mjs';
import { googleFlightEvidence, flightResultContent } from './lib/browser-flight-evidence.mjs';

// Verification-only policy: one requested advertised model, one small flight search, no accounts/payment.
const LIMITS = Object.freeze({ rounds: 24, calls: 24, deadlineMs: 180_000, historyMessages: 8, cleanupRetries: 10, cleanupDelayMs: 100 });
const [model, target, departureDate, outputPath] = process.argv.slice(2);
if (!model || !target || !/^\d{4}-\d{2}-\d{2}$/.test(departureDate || '') || !outputPath) throw new Error('Pass advertised free model ID, fixture or supplied flight URL, ISO departure date, and fresh output directory');
const output = path.resolve(outputPath); fs.mkdirSync(output); // Never overwrite earlier evidence.
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-flight-model-'));
process.env.CONFIG_DIR = path.join(root, 'config');
const { createSession } = await import('../src/core/bootstrap.mjs');
const { Agent } = await import('../src/core/agent.mjs');
const { loadSkills } = await import('../src/core/skills.mjs');
const { BrowserPluginStore } = await import('../src/integrations/browser-plugins.mjs');
const { PlaywrightBrowserAdapter } = await import('../tools/browser/playwright.mjs');
const { BrowserSessionManager } = await import('../tools/browser/session.mjs');
const fixture = target === 'fixture' ? await createFlightFixtureServer({ departureDate }) : null;
const url = fixture?.url || target;
const config = { provider: 'kilo', model, tools: true, apiKey: '', autoApprove: true, memoryConsolidation: false,
  memoryRecallChars: 0, historyMessages: LIMITS.historyMessages, maxToolSteps: LIMITS.rounds, maxToolCalls: LIMITS.calls,
  browserToolFocus: true, allowPrivateHosts: Boolean(fixture), browserRuntimeV2: false };
const adapter = new PlaywrightBrowserAdapter({ profile: path.join(root, 'profile') });
const store = new BrowserPluginStore(path.join(root, 'browser.json')).load(); store.setEnabled('isolated', true);
const manager = new BrowserSessionManager({ store, isolatedFactory: () => adapter });
const originalRequest = `Use the browser at ${url} to find one-way flights from Mumbai (BOM) to New Delhi (DEL) on ${departureDate}. Preserve this direction despite page defaults. Confirm the route, exact date and one-way type on the results page and report flight information. Stop at search results; leave them open. Do not book, choose a supplier, sign in or enter passenger/payment details.`;
const traceFile = path.join(output, 'trace.jsonl');
const trace = entry => fs.appendFileSync(traceFile, JSON.stringify(entry) + '\n');
const started = performance.now();
let agent, timer, summary = { model, target: fixture ? 'fixture' : url, departureDate, booking: false };
let toolReadVerified = false; // Model-visible current browser evidence must include prices and schedule, not just the host's read-back.
try {
  const session = await createSession({ config, login: async () => { throw new Error('This probe cannot authenticate'); } });
  assert.equal(session.model, model, 'no fallback model');
  assert.ok(session.client.freeOnly && !config.apiKey && session.models.some(entry => entry.id === model && entry.tools !== false), 'the supplied route must survive the keyless free-only catalogue gate with tools');
  config.contextWindow = session.picked.context;
  const skill = loadSkills().find(item => item.name === 'browser-use');
  agent = new Agent({ client: session.client, config, workspacePath: root, browserManager: manager, skillsEnabled: true,
    allowedTools: new Set(['browser', 'find_tools', 'skill']), toolContext: { settings: { headless: true } }, print: () => {}, write: () => {} });
  agent.state.activatedTools.add('browser'); // Exercise the already-discovered continuation path.
  agent.messages.push({ role: 'user', content: originalRequest }, { role: 'assistant', content: 'I will search using the browser.' });
  const nativeStream = agent.streamTurn.bind(agent);
  let rounds = 0;
  agent.streamTurn = async options => {
    const skillDelivered = agent.messages[0].content.includes(skill.body);
    const originalRetained = agent.messages.some(message => message.role === 'user' && message.content === originalRequest);
    trace({ event: 'model_request', round: ++rounds, skillDelivered, originalRetained });
    assert.ok(skillDelivered && originalRetained, 'actual model request must retain the complete guide and requested itinerary');
    const reply = await nativeStream(options); trace({ event: 'model_reply', round: rounds, content: reply.content, toolCalls: reply.toolCalls }); return reply;
  };
  timer = setTimeout(() => agent.abort?.abort(new Error('Small flight probe deadline')), LIMITS.deadlineMs);
  const reply = await agent.send('use browser', {
    onToolCall: call => trace({ event: 'tool_call', call }),
    onToolResult: (call, result) => {
      trace({ event: 'tool_result', id: call.id, result });
      if (call.function?.name === 'browser' && String(result).includes('/flights/search')) {
        const evidence = flightResultContent(result);
        if (evidence.priced && evidence.scheduled) toolReadVerified = true;
      }
    },
  });
  const browserOpen = adapter.page && !adapter.page.isClosed();
  const readBack = browserOpen ? await adapter.page.evaluate(() => ({ url: location.href,
    text: document.body.innerText, inputs: [...document.querySelectorAll('input')].map(input => ({ label: input.getAttribute('aria-label') || input.labels?.[0]?.textContent?.trim(), value: input.value })) })) : null;
  const observations = readBack?.text || '';
  summary = { ...summary, wallMs: Math.round(performance.now() - started), rounds, toolCalls: agent.totalToolCalls,
    skillAudit: agent.skillAudit, usage: agent.turnUsage, termination: agent.terminationReason, reply, readBack,
    searches: fixture?.searches ?? null, browserOpen: Boolean(browserOpen) };
  if (fixture) {
    summary.pass = fixture.searches.length === 1 && fixture.searches[0].origin === 'BOM' && fixture.searches[0].destination === 'DEL' &&
      fixture.searches[0].trip === 'One way' && fixture.searches[0].date === departureDate && /Flight results/.test(observations) && Boolean(browserOpen);
  } else {
    // Independent current form/read-back, not the model's narrative. URL confirms an actual results view.
    const evidence = googleFlightEvidence(readBack, departureDate);
    summary.checks = evidence.checks; summary.dateVerified = evidence.dateVerified;
    summary.toolReadVerified = toolReadVerified;
    summary.pass = evidence.pass && toolReadVerified; // Loading placeholders cannot certify a successful flight read.
  }
  trace({ event: 'final', ...summary });
  console.log('FLIGHT_MODEL_PROBE ' + JSON.stringify({ model, fixture: Boolean(fixture), pass: summary.pass, rounds, toolCalls: agent.totalToolCalls, wallMs: summary.wallMs, skill: agent.skillAudit, checks: summary.checks, dateVerified: summary.dateVerified, searches: fixture?.searches }));
  if (!summary.pass) process.exitCode = 1;
} catch (error) {
  summary = { ...summary, pass: false, error: error.message, wallMs: Math.round(performance.now() - started) };
  trace({ event: 'error', ...summary }); console.log('FLIGHT_MODEL_PROBE_FAILED ' + JSON.stringify(summary)); process.exitCode = 1;
} finally {
  clearTimeout(timer); fs.writeFileSync(path.join(output, 'summary.json'), JSON.stringify(summary, null, 2));
  await manager.close(); await fixture?.close();
  assert.equal(fs.realpathSync(path.dirname(root)), fs.realpathSync(os.tmpdir()));
  await fs.promises.rm(root, { recursive: true, force: true, maxRetries: LIMITS.cleanupRetries, retryDelay: LIMITS.cleanupDelayMs });
}
