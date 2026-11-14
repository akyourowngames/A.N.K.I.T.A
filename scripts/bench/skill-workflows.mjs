import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { once } from 'node:events';
import { fileURLToPath } from 'node:url';
import { ToolHost } from '../../src/core/tool-host.mjs';
import { loadSkills, activeAutomaticSkills } from '../../src/core/skills.mjs';
import { shutdownFileToolWorkers } from '../../src/tooling/tool-worker.mjs';

// Offline reference fixtures, not real devices, websites or model decisions.
const FIELD_NAMES = ['title', 'place', 'date', 'note'];
const REQUESTED = Object.fromEntries(FIELD_NAMES.map(name => [name, `${name} value`]));
const DEVICE = 'fixture-device';
const SERVER_ID = 'reference-phone';
const MOBILE_TOOLS = ['mobile_list_available_devices', 'mobile_list_elements_on_screen', 'mobile_click_on_screen_at_coordinates', 'mobile_type_keys', 'mobile_batch_commands'];
const BEFORE = 'status: old\n';
const AFTER = 'status: new\n';
const FILES = ['first.txt', 'second.txt', 'third.txt', 'fourth.txt'];

function calls(host) {
  const trace = [];
  return {
    trace,
    async call(name, args = {}) {
      trace.push({ name, args });
      const result = await host.execute({ id: `call-${trace.length}`, name, arguments: args });
      const text = result.content.filter(part => part.type === 'text').map(part => part.text).join('\n');
      assert.equal(result.isError, false, text);
      return text;
    },
  };
}

async function mobile(optimized, failure) {
  const values = Object.fromEntries(FIELD_NAMES.map(name => [name, '']));
  const writes = new Map();
  let focus, saved = false, failed = false;
  const observe = () => ({ values: { ...values }, refs: [...FIELD_NAMES, 'save'], saved });
  function primitive({ tool, args }) {
    if (tool === 'mobile_click_on_screen_at_coordinates') {
      assert.ok([...FIELD_NAMES, 'save'].includes(args.ref));
      if (args.ref === 'save') saved = true;
      else focus = args.ref;
    } else if (tool === 'mobile_type_keys') {
      assert.ok(focus);
      writes.set(focus, (writes.get(focus) || 0) + 1);
      values[focus] += args.text; // Append semantics expose accidental replay.
      if (failure && focus === FIELD_NAMES[1] && !failed) { failed = true; return { uncertain: true, reason: 'Timeout after write; read current values' }; }
    } else throw new Error(`Unexpected mobile primitive ${tool}`);
    return { completed: true };
  }
  const mcp = {
    summaries: () => [{ id: SERVER_ID, deferred: true, tools: MOBILE_TOOLS }],
    findTool: name => MOBILE_TOOLS.some(tool => name === `mcp__${SERVER_ID}__${tool}`) ? { tool: { annotations: {} } } : null,
    needsApproval: () => true,
    approvalDetail: name => name,
    async callToolResult(name, args) {
      const tool = name.split('__').at(-1);
      let result;
      if (tool === 'mobile_list_available_devices') result = { devices: [DEVICE] };
      else {
        assert.equal(args.device, DEVICE);
        if (tool === 'mobile_list_elements_on_screen') result = observe();
        else if (tool === 'mobile_batch_commands') {
          let completed = 0;
          for (const command of args.commands) {
            result = primitive(command);
            if (result.uncertain) break;
            completed++;
          }
          result = { ...result, completed, ...(args.returnElements ? { observation: observe() } : {}) };
        } else result = primitive({ tool, args });
      }
      return { content: [{ type: 'text', text: JSON.stringify(result) }] };
    },
  };
  const host = new ToolHost({ context: { config: { autoApprove: true }, skillsInteractive: true, mcp } });
  const driver = calls(host);
  const call = (name, args = {}) => driver.call(`mcp__${SERVER_ID}__${name}`, { device: DEVICE, ...args }).then(JSON.parse);
  await driver.call('find_tools', { query: SERVER_ID });
  if (optimized) assert.ok(activeAutomaticSkills(loadSkills(), host.requestState.activeSkillTools).some(skill => skill.name === 'mobile-mcp'), 'real discovery auto-loads instructions without a skill call');
  assert.deepEqual((await call('mobile_list_available_devices')).devices, [DEVICE]);
  let observation = await call('mobile_list_elements_on_screen');
  function remaining() {
    return FIELD_NAMES.filter(name => observation.values[name] !== REQUESTED[name]).flatMap(name => [
      { tool: 'mobile_click_on_screen_at_coordinates', args: { ref: name } },
      { tool: 'mobile_type_keys', args: { text: REQUESTED[name] } },
    ]).concat({ tool: 'mobile_click_on_screen_at_coordinates', args: { ref: 'save' } });
  }
  if (optimized) {
    let result = await call('mobile_batch_commands', { commands: remaining(), returnElements: true });
    if (result.uncertain) {
      observation = await call('mobile_list_elements_on_screen');
      result = await call('mobile_batch_commands', { commands: remaining(), returnElements: true });
    }
    observation = result.observation;
  } else {
    for (const command of remaining()) {
      const result = await call(command.tool, command.args);
      if (result.uncertain) observation = await call('mobile_list_elements_on_screen');
    }
    observation = await call('mobile_list_elements_on_screen');
  }
  assert.equal(observation.saved, true);
  assert.deepEqual(observation.values, REQUESTED);
  const duplicateWrites = [...writes.values()].reduce((total, count) => total + Math.max(0, count - 1), 0);
  assert.equal(duplicateWrites, 0);
  return { calls: driver.trace.length, trace: driver.trace, outcome: observation, duplicateWrites };
}

async function workspace(directory, optimized) {
  fs.mkdirSync(directory);
  for (const name of FILES) fs.writeFileSync(path.join(directory, name), BEFORE);
  const host = new ToolHost({ context: { cwd: directory, workspacePath: directory, config: { autoApprove: true }, skillsInteractive: true } });
  const driver = calls(host);
  if (optimized) await driver.call('skill', { name: 'workspace-batch' });
  for (const name of FILES) assert.match(await driver.call('read_file', { path: name }), /status: old/);
  if (optimized) {
    await driver.call('apply_patch', { patch: FILES.map(name => `--- a/${name}\n+++ b/${name}\n@@ -1 +1 @@\n-status: old\n+status: new\n`).join('') });
  } else for (const name of FILES) await driver.call('edit_file', { path: name, old_string: BEFORE, new_string: AFTER });
  const evidence = await driver.call('search_files', { pattern: '^status: new$', include: '*.txt' });
  for (const name of FILES) assert.ok(evidence.includes(name), `final readback includes ${name}`);
  return { calls: driver.trace.length, trace: driver.trace, outcome: FILES.map(name => fs.readFileSync(path.join(directory, name), 'utf8')) };
}

async function research(urls, optimized) {
  const driver = calls(new ToolHost({ context: { config: {}, skillsInteractive: true } }));
  if (optimized) await driver.call('skill', { name: 'research-brief' });
  const read = async url => {
    const result = JSON.parse(await driver.call('http_request', { url }));
    assert.equal(result.status, 200);
    return result.body;
  };
  const outcome = optimized ? await Promise.all(urls.map(read)) : [];
  if (!optimized) for (const url of urls) outcome.push(await read(url));
  assert.equal(outcome.length, urls.length);
  return { calls: driver.trace.length, trace: driver.trace, outcome };
}

export async function runSkillWorkflowBench() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'skill-workflow-bench-'));
  const server = http.createServer((req, res) => { res.setHeader('content-type', 'text/plain'); res.end(`Complete fixture evidence for ${req.url}`); });
  try {
    server.listen(0, '127.0.0.1');
    await once(server, 'listening');
    const base = `http://127.0.0.1:${server.address().port}`;
    const workloads = [];
    for (const [name, run] of [
      ['mobile-form', optimized => mobile(optimized, false)],
      ['mobile-recovery', optimized => mobile(optimized, true)],
      ['workspace', optimized => workspace(path.join(directory, optimized ? 'batch' : 'individual'), optimized)],
      ['research', optimized => research(['/one', '/two', '/three'].map(route => base + route), optimized)],
    ]) {
      const baseline = await run(false), optimized = await run(true);
      assert.deepEqual(optimized.outcome, baseline.outcome);
      workloads.push({ name, baselineCalls: baseline.calls, optimizedCalls: optimized.calls, equalOutcome: true, duplicateWrites: optimized.duplicateWrites ?? 0, baselineTrace: baseline.trace.map(item => item.name), optimizedTrace: optimized.trace.map(item => item.name) });
    }
    const baselineCalls = workloads.reduce((sum, item) => sum + item.baselineCalls, 0);
    const optimizedCalls = workloads.reduce((sum, item) => sum + item.optimizedCalls, 0);
    return { scope: 'scripted reference workflows; not model or physical-device performance', baseline: 'individual actions, same required reads and verification', baselineCalls, optimizedCalls, savingsPercent: (baselineCalls - optimizedCalls) / baselineCalls * 100, workloads };
  } finally {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
    shutdownFileToolWorkers();
    const relative = path.relative(fs.realpathSync(os.tmpdir()), fs.realpathSync(directory));
    assert.ok(relative && !relative.startsWith('..') && !path.isAbsolute(relative));
    fs.rmSync(directory, { recursive: true, force: true });
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  console.log(JSON.stringify(await runSkillWorkflowBench(), null, 2));
}
