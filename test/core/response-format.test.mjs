import test from 'node:test';
import assert from 'node:assert/strict';
import { buildSystemPrompt } from '../../src/core/agent.mjs';

test('the shared model prompt specifies a readable Markdown answer format', () => {
  const prompt = buildSystemPrompt({ agentName: 'Ankita', username: 'User' }, process.cwd());
  assert.match(prompt, /GitHub-flavored Markdown/);
  assert.match(prompt, /pipe table/i);
  assert.match(prompt, /fenced code block/i);
});
