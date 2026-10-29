import test from 'node:test';
import assert from 'node:assert/strict';
import { voiceActionContext, voiceResultConfirmation } from '../../src/automation/voice-progress.mjs';

test('progress facts keep only basename/program metadata, never command arguments or file bodies', () => {
  const context = voiceActionContext({ function: { name: 'run_command', arguments: JSON.stringify({
    command: '& "C:\\Program Files\\Editor\\editor.exe" "private note.txt" --token secret-value',
    path: 'private/poem.txt', content: 'PRIVATE FILE BODY', env: { TOKEN: 'secret-value' }, background: true,
  }) } });
  assert.deepEqual(context, { tool: 'run_command', target: 'poem.txt', program: 'editor.exe', background: true });
  assert.ok(!JSON.stringify(context).includes('secret-value'));
});

test('incomplete or shell-expression arguments do not become claimed executable names', () => {
  assert.deepEqual(voiceActionContext({ function: { name: 'write_file', arguments: '{' } }), { tool: 'write_file' });
  assert.deepEqual(voiceActionContext({ function: { name: 'run_command', arguments: JSON.stringify({ command: '$(get-program) --secret value' }) } }), { tool: 'run_command' });
});

test('a foreground command which yields a live job is only submitted, and failure remains failure', () => {
  const action = { tool: 'run_command', program: 'editor', background: false };
  assert.equal(voiceResultConfirmation(action, 'done', 'job 7: running after 1.0s', { ok: null }), 'submitted');
  assert.equal(action.background, true);
  assert.equal(voiceResultConfirmation(action, 'failed', 'job 7: running after 1.0s', { ok: false }), 'failed');
  assert.equal(voiceResultConfirmation({ tool: 'write_file' }, 'done', 'Created', { ok: true }), 'confirmed');
});
