import test from 'node:test';
import assert from 'node:assert/strict';
import { Agent, buildSystemPrompt } from '../src/agent.mjs';
import { capOutput } from '../tools/_shared.mjs';
import { isMutation, verdictFor, verificationFooter, isToolFailure } from '../src/verify.mjs';

const sendName = 'mcp__composio__COMPOSIO_MULTI_EXECUTE_TOOL';
const sendArgs = { tools: [{ tool_slug: 'GMAIL_SEND_EMAIL', arguments: { to: 'me@example.com', attachments: [{ filename: 'deck.pdf' }] } }] };

test('mutation classification excludes readers and includes writers and connected-app sends', () => {
  for (const name of ['read_file', 'skill', 'recall']) assert.equal(isMutation(name, {}), false, name);
  for (const name of ['write_file', 'edit_file']) assert.equal(isMutation(name, {}), true, name);
  const mcp = { needsApproval: () => false, findTool: () => ({ tool: { annotations: { readOnlyHint: true } } }) };
  assert.equal(isMutation(sendName, sendArgs, mcp), true, 'trusted Composio send is still a mutation');
  assert.equal(isMutation(sendName, { tools: [{ tool_slug: 'GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID', arguments: {} }] }, mcp), false);
});

test('Gmail attachment verdict requires response evidence, not request or success flag alone', () => {
  const result = attachments => JSON.stringify({ data: { results: [{ tool_slug: 'GMAIL_SEND_EMAIL', response: { successful: true, data: { messageId: 'm1', attachmentList: attachments } } }], error_count: 0, successful: true } });
  assert.equal(verdictFor(sendName, sendArgs, result([{ filename: 'deck.pdf' }])).ok, true);
  const missing = verdictFor(sendName, sendArgs, result([]));
  assert.equal(missing.ok, false);
  assert.match(missing.reason, /fetch the sent message/i);
  assert.equal(verdictFor(sendName, sendArgs, JSON.stringify({ data: { results: [], error_count: 1 }, successful: false })).ok, false);
  assert.equal(verdictFor('read_file', {}, 'file text'), null);
});

test('a read result in a batch cannot verify a later send or create action', () => {
  const batchedSend = {
    tools: [
      { tool_slug: 'GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID', arguments: { message_id: 'older' } },
      ...sendArgs.tools,
    ],
  };
  const sendResult = JSON.stringify({ data: { results: [
    { index: 0, tool_slug: 'GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID', response: { successful: true, data: { attachmentList: [{ filename: 'old.pdf' }] } } },
    { index: 1, tool_slug: 'GMAIL_SEND_EMAIL', response: { successful: true, data: { messageId: 'new', attachmentList: [] } } },
  ], error_count: 0 } });
  assert.equal(verdictFor(sendName, batchedSend, sendResult).ok, false);

  const driveArgs = { tools: [
    { tool_slug: 'GOOGLEDRIVE_GET_FILE', arguments: { file_id: 'old' } },
    { tool_slug: 'GOOGLEDRIVE_UPLOAD_FILE', arguments: { name: 'new.md' } },
  ] };
  const driveResult = JSON.stringify({ data: { results: [
    { index: 0, tool_slug: 'GOOGLEDRIVE_GET_FILE', response: { successful: true, data: { id: 'old' } } },
    { index: 1, tool_slug: 'GOOGLEDRIVE_UPLOAD_FILE', response: { successful: true, data: {} } },
  ], error_count: 0 } });
  assert.equal(verdictFor(sendName, driveArgs, driveResult).ok, false);
});

test('each mutation in a batch needs its own evidence', () => {
  const twoSends = { tools: [sendArgs.tools[0], sendArgs.tools[0]] };
  const sends = JSON.stringify({ data: { results: [
    { index: 0, tool_slug: 'GMAIL_SEND_EMAIL', response: { successful: true, data: { attachmentList: [{ filename: 'first.pdf' }] } } },
    { index: 1, tool_slug: 'GMAIL_SEND_EMAIL', response: { successful: true, data: { attachmentList: [] } } },
  ], error_count: 0 } });
  assert.equal(verdictFor(sendName, twoSends, sends).ok, false);

  const mixed = { tools: [sendArgs.tools[0], { tool_slug: 'GOOGLEDRIVE_UPLOAD_FILE', arguments: { name: 'file.md' } }] };
  const result = JSON.stringify({ data: { results: [
    { index: 0, tool_slug: 'GMAIL_SEND_EMAIL', response: { successful: true, data: { attachmentList: [{ filename: 'first.pdf' }] } } },
    { index: 1, tool_slug: 'GOOGLEDRIVE_UPLOAD_FILE', response: { successful: true, data: {} } },
  ], error_count: 0 } });
  assert.equal(verdictFor(sendName, mixed, result).ok, false);
});

test('explicit ok false overrides a returned file ID', () => {
  assert.equal(verdictFor('mcp__drive__GOOGLEDRIVE_CREATE_FILE', {}, '{"ok":false,"id":"old-file-id"}').ok, false);
});

test('Drive creation needs a file receipt and still asks to read back content', () => {
  const name = 'mcp__composio__COMPOSIO_MULTI_EXECUTE_TOOL';
  const args = { tools: [{ tool_slug: 'GOOGLEDRIVE_UPLOAD_FILE', arguments: { name: 'deck.md' } }] };
  assert.equal(verdictFor(name, args, '{"data":{"results":[{"response":{"successful":true,"data":{"id":"file-123"}}}],"error_count":0}}').ok, true);
  assert.equal(verdictFor(name, args, '{"data":{"results":[{"response":{"successful":true,"data":{}}}],"error_count":0}}').ok, false);
  const docArgs = { tools: [{ tool_slug: 'GOOGLEDOCS_CREATE_DOCUMENT_MARKDOWN', arguments: { title: 'Deck' } }] };
  assert.equal(verdictFor(name, docArgs, '{"data":{"results":[{"response":{"successful":true,"data":{"documentId":"doc-123"}}}],"error_count":0}}').ok, true);
});

test('failure detection and footer share the runtime error convention', () => {
  for (const result of ['Error: failed', 'Not run: limit', 'The user denied permission', 'Action cancelled by user.']) {
    assert.equal(isToolFailure(result), true);
    assert.equal(verdictFor('write_file', {}, result).ok, false);
  }
  assert.match(verificationFooter({ ok: false, reason: 'no attachment evidence' }), /UNVERIFIED.*read-back/i);
  assert.match(verificationFooter({ ok: true, evidence: 'attachmentList has deck.pdf' }), /verified: attachmentList/);
  assert.match(verificationFooter({ ok: null, reason: 'result needs a read-back' }), /UNVERIFIED/);
  assert.ok(Buffer.byteLength(verificationFooter({ ok: false, reason: 'x'.repeat(300) })) < 200);
});

test('long tool output retains structural failure evidence without leaking adjacent secrets', () => {
  const raw = 'A'.repeat(400) + '{"error_count":1,"success_count":0,"attachmentList":[],"api_key":"private-value"}' + 'Z'.repeat(400);
  const capped = capOutput(raw, 240);
  assert.ok(Buffer.byteLength(capped) <= 240);
  assert.match(capped, /error_count=1/);
  assert.match(capped, /attachmentList=\[\]/);
  assert.doesNotMatch(capped, /private-value/);
  assert.equal(verdictFor('write_file', {}, capped).ok, false, 'truncated failure evidence remains actionable');
  const mixed = capOutput('A'.repeat(400) + '{"error_count":0}' + 'M'.repeat(400) + '{"error_count":1}' + 'Z'.repeat(400), 220);
  assert.match(mixed, /error_count=1/, 'a later failure wins over an earlier success count');
});

test('agent tool reply and trace expose an unverified mutation', async () => {
  const agent = new Agent({ client: {}, config: { tools: true, autoApprove: true, agentDebug: true } });
  agent.runToolCall = async () => 'Error: write failed';
  let round = 0;
  agent.streamTurn = async () => ++round === 1
    ? { content: '', toolCalls: [{ id: 'w1', type: 'function', function: { name: 'write_file', arguments: '{"path":"a.txt","content":"x"}' } }] }
    : { content: 'I could not write it.', toolCalls: [] };
  const originalError = console.error;
  const events = [];
  console.error = line => { try { events.push(JSON.parse(line)); } catch {} };
  try {
    await agent.sendTurn('write it');
  } finally {
    console.error = originalError;
  }
  const reply = agent.messages.find(message => message.role === 'tool');
  assert.match(reply.content, /UNVERIFIED.*read-back/i);
  assert.equal(events.find(event => event.event === 'tool_result')?.verified, false);
  assert.match(buildSystemPrompt({}, process.cwd()), /read-back check/);
});

test('agent tool reply fits the configured output budget with a verdict', async () => {
  const agent = new Agent({ client: {}, config: { tools: true, autoApprove: true, maxToolChars: 80 } });
  agent.runToolCall = async () => 'Error: ' + 'x'.repeat(500);
  let round = 0;
  agent.streamTurn = async () => ++round === 1
    ? { content: '', toolCalls: [{ id: 'w1', type: 'function', function: { name: 'write_file', arguments: '{}' } }] }
    : { content: 'Unconfirmed.', toolCalls: [] };
  await agent.sendTurn('write it');
  const reply = agent.messages.find(message => message.role === 'tool');
  assert.ok(Buffer.byteLength(reply.content) <= 80, reply.content);
  assert.match(reply.content, /UNVERIFIED/);
});
