import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// A sandbox config dir so importing the engine never touches real state.
const SANDBOX = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-attach-'));
process.env.CONFIG_DIR = SANDBOX;
test.after(() => fs.rmSync(SANDBOX, { recursive: true, force: true }));

const { buildUserContent } = await import('../../src/core/agent.mjs');
const { attachmentPayload } = await import('../../desktop/electron/engine.mjs');
const { trimMessages, estimateImageBytes, imageDimensions } = await import('../../src/core/history.mjs');

const b64 = (text) => Buffer.from(text).toString('base64');

test('no attachments keeps the plain string content shape', () => {
  assert.equal(buildUserContent('hello', []), 'hello');
  assert.equal(buildUserContent('hello', null), 'hello');
});

test('a text attachment is folded into the prompt as a labelled block', () => {
  const content = buildUserContent('summarise this', [{ name: 'notes.md', text: '# Notes\nbody' }]);
  assert.ok(Array.isArray(content));
  assert.deepEqual(content[0], { type: 'text', text: 'summarise this' });
  assert.match(content[1].text, /Attached file: notes\.md/);
  assert.match(content[1].text, /# Notes/);
});

test('an image attachment becomes an image_url part for vision models', () => {
  const dataUrl = 'data:image/png;base64,AAAA';
  const content = buildUserContent('what is this', [{ name: 'shot.png', dataUrl }]);
  assert.deepEqual(content.at(-1), { type: 'image_url', image_url: { url: dataUrl } });
});

test('a lone text attachment with no prompt still produces usable content', () => {
  const content = buildUserContent('', [{ name: 'a.txt', text: 'body' }]);
  assert.ok(Array.isArray(content));
  assert.equal(content.length, 1);
  assert.match(content[0].text, /a\.txt/);
  assert.equal(content[0].type, 'text');
});

test('attachment payload decodes text and images and sanitises names', () => {
  const payload = attachmentPayload([
    { name: 'hello.txt', data: b64('hi there') },
    { name: 'pic.png', data: b64('fake-png-bytes') },
    { name: 'evil\nname.md', data: b64('x') },
  ]);
  assert.equal(payload[0].text, 'hi there');
  assert.match(payload[1].dataUrl, /^data:image\/png;base64,/);
  assert.equal(payload[2].name.includes('\n'), false, 'a newline cannot break out of the label');
});

test('attachment payload rejects unsupported, oversized and binary files', () => {
  assert.throws(() => attachmentPayload([{ name: 'virus.exe', data: b64('x') }]), /not a supported file type/);
  assert.throws(() => attachmentPayload([{ name: 'big.txt', data: Buffer.alloc(200 * 1024 + 1).toString('base64') }]), /larger than 200 KB/);
  assert.throws(() => attachmentPayload([{ name: 'binary.txt', data: Buffer.from([65, 0, 66]).toString('base64') }]), /looks binary/);
});

test('an empty payload is tolerated so a text-only send still works', () => {
  assert.deepEqual(attachmentPayload([]), []);
  assert.deepEqual(attachmentPayload(null), []);
});

test('scanned-page images ride along with the document payload', () => {
  const page = 'data:image/png;base64,AAAA';
  const payload = attachmentPayload([
    { name: 'scan.pdf', kind: 'document', data: b64('(scanned pages attached as images)'), images: [page, 'not-an-image'] },
  ]);
  assert.deepEqual(payload[0].images, [page], 'only data:image URLs survive');
});

test('page images are charged to the same context budget as text', () => {
  const bigPage = `data:image/png;base64,${'A'.repeat(400_000)}`;
  // Two ~300 KB pages (base64 length × .75) exceed a tiny window's 35% share.
  assert.throws(
    () => attachmentPayload([{ name: 'scan.pdf', kind: 'document', data: b64('x'), images: [bigPage, bigPage] }], { contextWindow: 1000 }),
    /context budget/,
  );
});

test('trimMessages drops image parts before failing the turn', () => {
  const hugeUrl = `data:image/png;base64,${'B'.repeat(50_000)}`;
  const messages = [
    { role: 'user', content: [{ type: 'image_url', image_url: { url: hugeUrl } }, { type: 'text', text: 'Attached file: scan.pdf\n```\nok\n```' }] },
  ];
  const result = trimMessages(messages, 40, 8_000);
  const parts = result.find(m => m.role === 'user').content;
  assert.ok(!parts.some(p => p.type === 'image_url'), 'the image was dropped');
  assert.ok(parts.some(p => p.type === 'text'), 'the text attachment survives');
});

/** Minimal image bytes with correct dimensions and arbitrary trailing bytes. */
function imageDataUrl(kind, width, height, fillerLength = 0) {
  let header;
  if (kind === 'png') {
    header = Buffer.alloc(33);
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]).copy(header, 0);
    header.writeUInt32BE(13, 8);
    header.write('IHDR', 12, 'latin1');
    header.writeUInt32BE(width, 16);
    header.writeUInt32BE(height, 20);
    header[24] = 8;
    header[25] = 2;
  } else if (kind === 'gif') {
    header = Buffer.alloc(10);
    header.write('GIF89a', 0, 'latin1');
    header.writeUInt16LE(width, 6);
    header.writeUInt16LE(height, 8);
  } else if (kind === 'jpg') {
    header = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xff, 0xc0, 0x00, 0x0b]);
    const dimensions = Buffer.alloc(9);
    dimensions[0] = 8;
    dimensions.writeUInt16BE(height, 1);
    dimensions.writeUInt16BE(width, 3);
    dimensions[5] = 1;
    header = Buffer.concat([header, dimensions]);
  } else if (kind === 'webp') {
    header = Buffer.alloc(30);
    header.write('RIFF', 0, 'latin1');
    header.write('WEBP', 8, 'latin1');
    header.write('VP8L', 12, 'latin1');
    header[20] = 0x2f;
    header.writeUInt32LE((((height - 1) << 14) | (width - 1)) >>> 0, 21);
  } else {
    throw new Error(`unsupported test image: ${kind}`);
  }
  const bytes = fillerLength ? Buffer.concat([header, Buffer.alloc(fillerLength, 0x41)]) : header;
  const mime = kind === 'jpg' ? 'jpeg' : kind;
  return `data:image/${mime};base64,${bytes.toString('base64')}`;
}

test('supported image dimensions are read for vision-token budgeting', () => {
  assert.deepEqual(imageDimensions(imageDataUrl('png', 1700, 2200)), { width: 1700, height: 2200 });
  assert.deepEqual(imageDimensions(imageDataUrl('jpg', 1600, 900)), { width: 1600, height: 900 });
  assert.deepEqual(imageDimensions(imageDataUrl('gif', 64, 48)), { width: 64, height: 48 });
  assert.deepEqual(imageDimensions(imageDataUrl('webp', 320, 240)), { width: 320, height: 240 });
  assert.equal(imageDimensions('data:image/png;base64,AAAA'), null);
});

test('a large but decodable image is budgeted by pixels rather than upload bytes', () => {
  const url = imageDataUrl('png', 1700, 2200, 100_000);
  assert.ok(Buffer.byteLength(url) > 100_000);
  assert.ok(estimateImageBytes(url) < 5_000);
  const payload = attachmentPayload([{ name: 'certificate.png', data: url.split(',')[1] }]);
  assert.equal(payload[0].dataUrl, url);
});

test('trimMessages preserves a decodable image that fits as visual tokens', () => {
  const url = imageDataUrl('png', 1700, 2200, 100_000);
  const messages = [
    { role: 'user', content: [{ type: 'image_url', image_url: { url } }, { type: 'text', text: 'whats this' }] },
  ];
  const result = trimMessages(messages, 40, 8_000);
  const parts = result.find(m => m.role === 'user').content;
  assert.ok(parts.some(p => p.type === 'image_url'), 'the certificate image must reach the model');
});

test('document pages that do not all fit keep their leading pages with a note', () => {
  const images = Array.from({ length: 7 }, () => imageDataUrl('png', 1, 1));
  const payload = attachmentPayload(
    [{ name: 'scan.pdf', kind: 'document', data: b64('x'), images }],
    { contextWindow: 1000 },
  );
  assert.equal(payload[0].images.length, 5);
  assert.match(payload[0].text, /attached pages 1-5 of 7/);
});
