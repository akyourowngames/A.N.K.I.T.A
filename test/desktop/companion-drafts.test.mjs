import test from 'node:test';
import assert from 'node:assert/strict';
import { CompanionDrafts } from '../../desktop/shared/companion-drafts.mjs';
import { MAX_ATTACHMENTS } from '../../desktop/browser-helper/protocol.mjs';
test('an asynchronous reader preserves the receiving teammate and both text drafts', async () => {
  const store = new CompanionDrafts(); let complete;
  store.update('chief', draft => ({ ...draft, text: 'Original draft' }));
  const pending = store.read('chief', [{name: 'note.md'}], () => new Promise(resolve => { complete = resolve; }));
  store.update('research', draft => ({ ...draft, text: 'Different selected teammate' }));
  complete({name: 'note.md', image: false, data: 'bm90ZQ=='});
  assert.equal((await pending).accepted, 1);
  assert.equal(store.get('chief').files[0].name, 'note.md');
  assert.equal(store.get('chief').text, 'Original draft');
  assert.equal(store.get('research').files.length, 0);
  assert.equal(store.get('research').text, 'Different selected teammate');
});
test('capture receipts deduplicate and concurrent file/page results enforce the real cap', async () => {
  const store = new CompanionDrafts(); let complete;
  const file = {name: 'fixture.txt', image: false, data: ''};
  store.update('chief', draft => ({ ...draft, files: Array(MAX_ATTACHMENTS - 1).fill(file) }));
  const pending = store.read('chief', [file], () => new Promise(resolve => { complete = resolve; }));
  const receipt = {id: 'one', threadId: 'chief', attachment: file};
  assert.equal(store.capture(receipt), true);
  assert.equal(store.capture(receipt), true);
  complete(file);
  assert.equal((await pending).accepted, 0);
  assert.equal(store.get('chief').files.length, MAX_ATTACHMENTS);
  assert.equal(store.capture({...receipt, id: 'two'}), false);
  assert.equal(store.get('chief').reading, false);
});
test('unreadable files settle the reader and expose its real error', async () => {
  const store = new CompanionDrafts();
  const result = await store.read('chief', [{name: 'bad.bin'}], async () => { throw new Error('Unsupported file'); });
  assert.equal(result.accepted, 0);
  assert.match(store.get('chief').error, /Unsupported file/);
  assert.equal(store.get('chief').reading, false);
});
