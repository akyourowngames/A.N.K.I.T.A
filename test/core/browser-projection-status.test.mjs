import test from 'node:test';
import assert from 'node:assert/strict';
import { compactBrowserHistory } from '../../src/core/browser-context.mjs';

test('request projection preserves failed partial batches and every paired tool reply', () => {
  const call = id => ({ role: 'assistant', content: null, tool_calls: [{ id, function: { name: 'browser', arguments: '{}' } }] });
  const partial = '1. click complete.\nCurrent snapshot:\nOld page — https://fixture.test/a\n[ref=1-0-0] button Save\n2. Error: stale target. Batch stopped.\n[UNVERIFIED: tool reported a failure. Do not claim success.]';
  const messages = [call('partial'), { role: 'tool', tool_call_id: 'partial', content: partial },
    call('latest'), { role: 'tool', tool_call_id: 'latest', content: 'Current — https://fixture.test/b\n[ref=2-0-0] button Next' }];
  const projected = compactBrowserHistory(messages);
  assert.equal(projected[1].content, partial);
  assert.equal(messages[1].content, partial);
  assert.deepEqual(projected.filter(message => message.role === 'tool').map(message => message.tool_call_id), ['partial', 'latest']);
});

test('evidence projection leaves the latest partial failure receipt intact', () => {
  const call = id => ({ role: 'assistant', tool_calls: [{ id, function: { name: 'browser' } }] });
  const partial = '1. fill complete.\n2. Error: target changed. Batch stopped.';
  const messages = [call('read'), { role: 'tool', tool_call_id: 'read', content: 'Observed source' }, call('partial'), { role: 'tool', tool_call_id: 'partial', content: partial }];
  const projected = compactBrowserHistory(messages, { evidence: [{ sourceUrl: 'https://fixture.test/a', observationId: 'source', text: 'Price 19' }] });
  assert.equal(projected.at(-1).content, partial);
  assert.match(projected[1].content, /Price 19/);
});
