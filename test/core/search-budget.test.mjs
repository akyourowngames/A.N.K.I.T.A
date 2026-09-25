import test from 'node:test';
import assert from 'node:assert/strict';
import { Agent, MAX_WEB_SEARCHES_PER_TURN } from '../../src/core/agent.mjs';

const call = query => ({ function: { name: 'web_search', arguments: JSON.stringify({ query }) } });

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
