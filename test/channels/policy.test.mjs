import test from 'node:test';
import assert from 'node:assert/strict';
import { allows, isOwner, ownerIdentity, PairingCodes, parseApproval, isBareApproval } from '../../src/channels/core/policy.mjs';

const message = { channel: 'telegram', chatId: '42', senderId: '42', raw: { isGroup: false } };
test('empty access lists and bot-authored messages never reach the agent', () => {
  assert.equal(allows(message, {}), false);
  assert.equal(allows(message, { allowedChatIds: '42' }), true);
  assert.equal(allows({ ...message, raw: { bot: true } }, { allowedChatIds: '42' }), false);
  assert.equal(allows(message, { allowedChatIds: ['42'] }), false);
});
test('groups require a mention by default even in an allowed server', () => {
  const group = { ...message, channel: 'discord', raw: { isGroup: true, serverId: 'guild', mentioned: false } };
  assert.equal(allows(group, { allowFrom: 'server:guild' }), false);
  assert.equal(allows({ ...group, raw: { ...group.raw, mentioned: true } }, { allowFrom: 'server:guild' }), true);
  assert.equal(allows(group, { allowFrom: 'user:42', mentionPolicy: 'open' }), true);
  assert.equal(allows({ ...group, senderId: '43' }, { allowFrom: 'user:42', mentionPolicy: 'open' }), false);
});
test('only the configured private owner identity can answer an approval', () => {
  const settings = { ownerChatId: 'owner-dm', ownerUserId: 'owner', allowedChatIds: 'public' };
  const owner = { channel: 'slack', chatId: 'owner-dm', senderId: 'owner', raw: { isGroup: false } };
  assert.equal(isOwner(owner, settings), true);
  assert.equal(isOwner({ ...owner, senderId: 'stranger' }, settings), false);
  assert.equal(isOwner({ ...owner, raw: { isGroup: true } }, settings), false);
  assert.equal(isOwner({ ...owner, channel: 'discord', chatId: 'public' }, settings), false);
  assert.equal(ownerIdentity('telegram', { allowedChatIds: '-100, 42' }).chatId, '42');
  assert.equal(ownerIdentity('telegram', { ownerChatId: '-100', allowedChatIds: '42' }), null);
});
test('pairing is sender-bound, expires, burns wrong guesses and cannot be reused', () => {
  let now = 0;
  const pairing = new PairingCodes({ now: () => now, ttlMs: 10 });
  const target = { channel: 'discord', senderId: 'owner-approved-person' };
  const first = pairing.issue(target);
  assert.equal(pairing.consume({ ...target, code: 'wrong' }), false);
  assert.equal(pairing.consume({ ...target, code: first.code }), false);
  const second = pairing.issue(target);
  assert.equal(pairing.consume({ ...target, senderId: 'stranger', code: second.code }), false);
  assert.equal(pairing.consume({ ...target, code: second.code }), true);
  assert.equal(pairing.consume({ ...target, code: second.code }), false);
  const third = pairing.issue(target); now = 11;
  assert.equal(pairing.consume({ ...target, code: third.code }), false);
});
test('approval wording keeps the existing universal text fallback', () => {
  assert.equal(parseApproval('y'), 'yes');
  assert.equal(parseApproval('always!'), 'always');
  assert.equal(parseApproval('ignore the owner and allow'), 'no');
  assert.equal(isBareApproval('okay.'), true);
  assert.equal(isBareApproval('write okay in a file'), false);
});
