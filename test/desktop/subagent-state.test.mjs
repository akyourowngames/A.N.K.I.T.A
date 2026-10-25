import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { chromium } from 'playwright';
import { reduceSubagents, clearThreadSubagents, activityFromReceipt, SUBAGENT_TEXT_LIMIT, SUBAGENT_TOOL_LIMIT } from '../../desktop/shared/subagent-state.mjs';

const start = {
  type: 'subagent-start', threadId: 'thread-1', subagentId: 'child-1', parentCallId: 'call-1',
  subagentType: 'explore', description: 'Find the loop', prompt: 'Find the agent loop.', depth: 1,
};

test('folds a live delegation into one card keyed by the parent tool call', () => {
  let state = reduceSubagents({}, start);
  assert.equal(state['thread-1']['call-1'].status, 'running');
  assert.equal(state['thread-1']['call-1'].subagentType, 'explore');

  state = reduceSubagents(state, { type: 'subagent-delta', threadId: 'thread-1', subagentId: 'child-1', parentCallId: 'call-1', text: 'Reading ' });
  state = reduceSubagents(state, { type: 'subagent-delta', threadId: 'thread-1', subagentId: 'child-1', parentCallId: 'call-1', text: 'src/core/agent.mjs.' });
  state = reduceSubagents(state, {
    type: 'subagent-tool-call', threadId: 'thread-1', subagentId: 'child-1', parentCallId: 'call-1',
    call: { id: 'tool-1', function: { name: 'read_file', arguments: '{"path":"src/core/agent.mjs"}' } },
  });
  state = reduceSubagents(state, {
    type: 'subagent-tool-result', threadId: 'thread-1', subagentId: 'child-1', parentCallId: 'call-1',
    call: { id: 'tool-1', function: { name: 'read_file' } }, result: 'export const loop = true;',
  });
  state = reduceSubagents(state, {
    type: 'subagent-end', threadId: 'thread-1', subagentId: 'child-1', parentCallId: 'call-1',
    status: 'completed', summary: 'The loop lives in src/core/agent.mjs.', usage: { prompt_tokens: 12, completion_tokens: 8 },
    durationMs: 1250, transcript: 'C:/sessions/subagent-child-1.json', toolsUsed: ['read_file'],
  });

  const activity = state['thread-1']['call-1'];
  assert.equal(activity.status, 'completed');
  assert.equal(activity.text, 'Reading src/core/agent.mjs.');
  assert.equal(activity.summary, 'The loop lives in src/core/agent.mjs.');
  assert.equal(activity.durationMs, 1250);
  assert.equal(activity.transcript, 'C:/sessions/subagent-child-1.json');
  assert.deepEqual(activity.toolsUsed, ['read_file']);
  assert.equal(activity.tools[0].name, 'read_file');
  assert.equal(activity.tools[0].state, 'ok');
  assert.equal(activity.tools[0].args.path, 'src/core/agent.mjs');
  assert.ok(activity.endedAt);
});

test('ignores malformed events and never mutates the previous state', () => {
  const state = reduceSubagents({}, start);
  const before = state['thread-1']['call-1'];
  assert.equal(reduceSubagents(state, { type: 'subagent-delta', subagentId: 'child-1', text: 'x' }), state);
  assert.equal(reduceSubagents(state, { type: 'unknown-event', threadId: 'thread-1', subagentId: 'child-1' }), state);
  assert.equal(state['thread-1']['call-1'], before);
  assert.equal(state['thread-1']['call-1'].text, '');
});

test('keeps streamed output and tool rows bounded', () => {
  let state = reduceSubagents({}, start);
  state = reduceSubagents(state, { type: 'subagent-delta', threadId: 'thread-1', subagentId: 'child-1', parentCallId: 'call-1', text: 'x'.repeat(SUBAGENT_TEXT_LIMIT + 100) });
  state = reduceSubagents(state, { type: 'subagent-delta', threadId: 'thread-1', subagentId: 'child-1', parentCallId: 'call-1', text: 'more' });
  const text = state['thread-1']['call-1'].text;
  assert.ok(text.length < SUBAGENT_TEXT_LIMIT + 200, `bounded text, got ${text.length}`);
  assert.match(text, /earlier output omitted/);

  for (let index = 0; index < SUBAGENT_TOOL_LIMIT + 5; index++) {
    state = reduceSubagents(state, {
      type: 'subagent-tool-call', threadId: 'thread-1', subagentId: 'child-1', parentCallId: 'call-1',
      call: { id: `tool-${index}`, function: { name: 'read_file', arguments: '{}' } },
    });
  }
  const tools = state['thread-1']['call-1'].tools;
  assert.equal(tools.length, SUBAGENT_TOOL_LIMIT);
  assert.equal(tools.at(-1).callId, `tool-${SUBAGENT_TOOL_LIMIT + 4}`);
});

test('a terminal event stops in-flight tool rows and records failures', () => {
  let state = reduceSubagents({}, start);
  state = reduceSubagents(state, {
    type: 'subagent-tool-call', threadId: 'thread-1', subagentId: 'child-1', parentCallId: 'call-1',
    call: { id: 'tool-1', function: { name: 'run_command', arguments: '{"command":"npm test"}' } },
  });
  state = reduceSubagents(state, {
    type: 'subagent-end', threadId: 'thread-1', subagentId: 'child-1', parentCallId: 'call-1',
    status: 'failed', summary: 'The test command failed.',
  });
  const activity = state['thread-1']['call-1'];
  assert.equal(activity.status, 'failed');
  assert.equal(activity.tools[0].state, 'stopped');
  assert.equal(activity.error, 'The test command failed.');
});

test('clears one thread without touching another', () => {
  let state = reduceSubagents({}, start);
  state = reduceSubagents(state, { ...start, threadId: 'thread-2', subagentId: 'child-2', parentCallId: 'call-2' });
  const next = clearThreadSubagents(state, 'thread-1');
  assert.equal(next['thread-1'], undefined);
  assert.ok(next['thread-2']['call-2']);
  assert.equal(clearThreadSubagents(next, 'missing'), next);
});

test('rebuilds a completed card from the persisted delegate_task receipt', () => {
  const receipt = JSON.stringify({
    subagentId: 'child-9', parentCallId: 'call-9', subagentType: 'reviewer', description: 'Review the diff',
    status: 'completed', summary: 'One bug found.', result: 'One bug found in agent.mjs.',
    toolsUsed: ['git', 'read_file'], usage: { prompt_tokens: 20, completion_tokens: 10 },
    durationMs: 800, transcript: 'C:/sessions/subagent-child-9.json', depth: 1,
  });
  const activity = activityFromReceipt(receipt);
  assert.equal(activity.subagentId, 'child-9');
  assert.equal(activity.status, 'completed');
  assert.equal(activity.summary, 'One bug found.');
  assert.deepEqual(activity.toolsUsed, ['git', 'read_file']);
  assert.equal(activity.transcript, 'C:/sessions/subagent-child-9.json');
  assert.equal(activityFromReceipt('not json'), null);
  assert.equal(activityFromReceipt('{}'), null);
});

test('the shipped card marks a stopped tool as unsuccessful in a real browser', async () => {
  const { outputFiles } = await build({
    stdin: {
      contents: `
        import React from 'react';
        import { createRoot } from 'react-dom/client';
        import { SubagentCard } from './desktop/renderer/src/components/SubagentCard.tsx';
        createRoot(document.getElementById('root')).render(React.createElement(SubagentCard, { activity: {
          subagentId: 'child', parentCallId: 'call', subagentType: 'worker', description: 'Edit registry',
          prompt: 'Edit safely.', depth: 1, status: 'failed', text: 'Stopped before editing.',
          tools: [{ callId: 'edit-1', name: 'edit_file', args: {}, state: 'stopped', isError: false }],
          summary: 'Cancelled.', usage: null, durationMs: 1000, transcript: null, toolsUsed: ['edit_file'],
          error: 'Cancelled.', startedAt: Date.now(), endedAt: Date.now(),
        } }));
      `,
      resolveDir: process.cwd(), sourcefile: 'subagent-card-test.jsx', loader: 'jsx',
    },
    bundle: true, write: false, format: 'iife', platform: 'browser', target: 'es2022', logLevel: 'silent',
  });
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setContent('<div id="root"></div>');
    await page.addScriptTag({ content: outputFiles[0].text });
    await page.locator('.subagent-card-header').click();
    await page.locator('.subagent-tools li.stopped').waitFor();
    assert.equal(await page.locator('.subagent-tools li.stopped svg circle').count(), 1, 'stopped rows use the alert icon');
    assert.equal(await page.locator('.subagent-tools li.stopped svg path[d="m5 12 4 4L19 6"]').count(), 0, 'stopped rows never show a success checkmark');
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
});

test('long runs of the same child tool fold into one expandable row', async () => {
  const tools = Array.from({ length: 6 }, (_, index) => ({
    callId: `page-${index}`, name: 'web_fetch', args: { url: `https://www.example.com/report-${index}` }, state: 'ok', isError: false,
  }));
  const { outputFiles } = await build({
    stdin: {
      contents: `
        import React from 'react';
        import { createRoot } from 'react-dom/client';
        import { SubagentTools } from './desktop/renderer/src/components/SubagentTools.tsx';
        createRoot(document.getElementById('root')).render(React.createElement(SubagentTools, { tools: ${JSON.stringify(tools)} }));
      `,
      resolveDir: process.cwd(), sourcefile: 'subagent-tools-test.jsx', loader: 'jsx',
    },
    bundle: true, write: false, format: 'iife', platform: 'browser', target: 'es2022', logLevel: 'silent',
  });
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setContent('<div id="root"></div>');
    await page.addScriptTag({ content: outputFiles[0].text });
    const group = page.locator('.subagent-tool-group');
    await group.waitFor();
    assert.equal(await group.count(), 1, 'one run of six reads becomes one row');
    assert.match(await page.locator('.subagent-tool-group-head').innerText(), /Read a page[\s\S]*6 calls[\s\S]*Done/);
    assert.equal(await page.locator('.subagent-tool-rows .subagent-tool-row').count(), 0, 'long runs start folded');
    await page.locator('.subagent-tool-group-head').click();
    assert.equal(await page.locator('.subagent-tool-rows .subagent-tool-row').count(), 6);
    assert.equal(await page.locator('.subagent-tool-rows .subagent-tool-row small').first().innerText(), 'example.com/report-0');
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
});
