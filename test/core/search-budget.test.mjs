import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { randomUUID } from 'node:crypto';
import { Agent, MAX_WEB_SEARCHES_PER_TURN } from '../../src/core/agent.mjs';
import { JOB_EXECUTION_COMPLETE, JOB_EXECUTION_BOUNDED } from '../../src/automation/job-policy.mjs';

const call = query => ({ function: { name: 'web_search', arguments: JSON.stringify({ query }) } });

test('completion workers retain web search beyond the foreground request ceiling', async () => {
  const agent = new Agent({ client: {}, config: { tools: true, backgroundJob: true, backgroundExecutionPolicy: JOB_EXECUTION_COMPLETE }, deferTools: false, skillsEnabled: false });
  for (let index = 0; index <= MAX_WEB_SEARCHES_PER_TURN; index++) {
    assert.match(await agent.runToolCall(call('')), /query.*required/, 'the call reaches query validation rather than a fixed search limit');
  }
  assert.equal(agent.currentSpecs().some(spec => spec.function?.name === 'web_search'), true);
  assert.doesNotMatch(agent.messages[0].content, /Use at most \d+ web_search/);
});

test('explicitly bounded workers retain the foreground web-search ceiling', async () => {
  const agent = new Agent({ client: {}, config: { tools: true, backgroundJob: true, backgroundExecutionPolicy: JOB_EXECUTION_BOUNDED }, deferTools: false, skillsEnabled: false });
  agent.searchesThisTurn = MAX_WEB_SEARCHES_PER_TURN;
  assert.match(await agent.runToolCall(call('latest AI news')), /Search limit reached/);
  assert.equal(agent.currentSpecs().some(spec => spec.function?.name === 'web_search'), false);
});

test('completion search executes native calls through HTTP beyond six searches', async t => {
  const callsNeeded = MAX_WEB_SEARCHES_PER_TURN + 1;
  const queryPrefix = randomUUID();
  let received = 0, rounds = 0;
  const server = http.createServer((request, response) => {
    const query = new URL(request.url, 'http://fixture.test').searchParams.get('srsearch');
    assert.ok(query.startsWith(queryPrefix));
    received++;
    response.setHeader('Content-Type', 'application/json');
    response.end(JSON.stringify({ query: { search: [{ title: `Observed resource ${received}`, snippet: `Current reading ${received}` }] } }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve)); // Ephemeral loopback port is fixture-only.
  t.after(() => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }));
  const fixtureOrigin = `http://127.0.0.1:${server.address().port}`;
  const originalFetch = globalThis.fetch;
  t.mock.method(globalThis, 'fetch', (url, options) => {
    const requested = new URL(url);
    assert.equal(requested.hostname, 'en.wikipedia.org');
    return originalFetch(`${fixtureOrigin}${requested.pathname}${requested.search}`, options);
  });
  const agent = new Agent({ client: {}, config: { tools: true, backgroundJob: true, backgroundExecutionPolicy: JOB_EXECUTION_COMPLETE, memoryConsolidation: false },
    deferTools: false, skillsEnabled: false, allowedTools: new Set(['web_search']), print: () => {}, write: () => {} });
  agent.streamTurn = async () => {
    assert.ok(agent.currentSpecs().some(spec => spec.function?.name === 'web_search'));
    return ++rounds <= callsNeeded ? { content: '', toolCalls: [{ id: `search-${rounds}`, function: { name: 'web_search', arguments: JSON.stringify({ query: `${queryPrefix} resource ${rounds}`, backend: 'wikipedia' }) } }] }
      : { content: 'All resource readings observed.', toolCalls: [] };
  };
  assert.equal(await agent.send('Observe each resource and finish the task.'), 'All resource readings observed.');
  assert.equal(received, callsNeeded); assert.equal(agent.searchesThisTurn, callsNeeded); assert.equal(agent.terminationReason, null);
  assert.ok(agent.messages.filter(message => message.role === 'tool').every(message => /Current reading/.test(message.content)));
  console.log(`LIVE_COMPLETION_SEARCH_OK: ${received} native calls; HTTP fixture returned every resource; task completed`);
});

test('web searches stop at the per-request limit and reset for the next request', async () => {
  const agent = new Agent({ client: {}, config: { tools: true, agentName: 'Ankita', username: 'User' }, deferTools: false });
  for (let index = 0; index < MAX_WEB_SEARCHES_PER_TURN; index++) {
    assert.match(await agent.runToolCall(call('')), /query.*required/);
  }
  assert.match(await agent.runToolCall(call('latest AI news')), /Search limit reached/);
  assert.equal(agent.currentSpecs().some(spec => spec.function?.name === 'web_search'), false);
  agent.useTools = false;
  agent.sendTurn = async () => 'done';
  await agent.send('another request');
  assert.equal(agent.searchesThisTurn, 0);
  assert.match(await agent.runToolCall(call('')), /query.*required/);
});
