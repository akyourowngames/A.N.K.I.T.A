import test from 'node:test';
import assert from 'node:assert/strict';
import zlib from 'node:zlib';

const { sanitizeMessages } = await import('../../src/core/history.mjs');
const { threadMessages, attachmentPayload } = await import('../../desktop/electron/engine.mjs');
const { readZipEntries, extractDocumentText, pdfText, pdfTextCoverage, looksLikeProse } = await import('../../desktop/renderer/src/lib/extract-document.ts');

/* --------------------------- history keeps attachments ------------------- */

test('a user turn with multimodal content survives history sanitizing', () => {
  const messages = [
    { role: 'system', content: 'sys' },
    { role: 'user', content: [{ type: 'text', text: 'what is this' }, { type: 'image_url', image_url: { url: 'data:image/png;base64,AAAA' } }] },
    { role: 'assistant', content: 'A picture' },
  ];
  const clean = sanitizeMessages(messages);
  const user = clean.find(m => m.role === 'user');
  assert.ok(user, 'the attachment turn must not be dropped');
  assert.ok(Array.isArray(user.content));
  assert.equal(user.content.length, 2);
});

test('a plain user turn is still stored as a string', () => {
  const clean = sanitizeMessages([{ role: 'user', content: 'hello' }]);
  assert.deepEqual(clean, [{ role: 'user', content: 'hello' }]);
});

/* ---------------------- the transcript shows attachments ---------------- */

test('threadMessages recovers attachment chips from prompt blocks', () => {
  const transcript = threadMessages([
    { role: 'user', content: [
      { type: 'text', text: 'summarise this' },
      { type: 'text', text: 'Attached file: Proteus Arc.md\n```\nbody\n```' },
    ] },
    { role: 'user', content: [{ type: 'image_url', image_url: { url: 'data:image/png;base64,AAAA' } }] },
  ]);
  assert.equal(transcript[0].attachments[0].name, 'Proteus Arc.md');
  assert.equal(transcript[1].attachments[0].image, true);
});

/* -------------------------- document extraction ------------------------- */

/** Build a minimal ZIP with the given stored (uncompressed) entries. */
function makeZip(entries) {
  const chunks = [];
  const central = [];
  let offset = 0;
  for (const [name, text] of entries) {
    const nameBytes = Buffer.from(name);
    const data = Buffer.from(text);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(0, 8);   // stored
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(nameBytes.length, 26);
    chunks.push(local, nameBytes, data);
    const dir = Buffer.alloc(46);
    dir.writeUInt32LE(0x02014b50, 0);
    dir.writeUInt16LE(0, 10);    // stored
    dir.writeUInt32LE(data.length, 20);
    dir.writeUInt16LE(nameBytes.length, 28);
    dir.writeUInt32LE(offset, 42);
    central.push(Buffer.concat([dir, nameBytes]));
    offset += local.length + nameBytes.length + data.length;
  }
  const dirBuf = Buffer.concat(central);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(dirBuf.length, 12);
  end.writeUInt32LE(offset, 16);
  return new Uint8Array(Buffer.concat([...chunks, dirBuf, end]));
}

test('a docx-style zip is read and its text extracted', async () => {
  const zip = makeZip([['word/document.xml', '<w:document><w:p><w:r><w:t>Hello</w:t></w:r></w:p><w:p><w:r><w:t>World</w:t></w:r></w:p></w:document>']]);
  assert.deepEqual(readZipEntries(zip).map(e => e.name), ['word/document.xml']);
  const text = await extractDocumentText('notes.docx', zip);
  assert.match(text, /Hello/);
  assert.match(text, /World/);
});

test('an xlsx-style zip pulls shared strings', async () => {
  const zip = makeZip([
    ['xl/sharedStrings.xml', '<sst><si><t>Revenue</t></si></sst>'],
    ['xl/worksheets/sheet1.xml', '<worksheet><row><c><v>42</v></c></row></worksheet>'],
  ]);
  const text = await extractDocumentText('sheet.xlsx', zip);
  assert.match(text, /Revenue/);
  assert.match(text, /42/);
});

test('a text-showing PDF operator yields readable text', async () => {
  const pdf = Buffer.from('%PDF-1.4\nstream\nBT /F1 24 Tf (Hello from a PDF) Tj ET\nendstream\n%%EOF', 'latin1');
  const text = await pdfText(new Uint8Array(pdf));
  assert.match(text, /Hello from a PDF/);
});

test('a deflated PDF stream is inflated before reading text', async () => {
  const body = zlib.deflateSync(Buffer.from('BT (Compressed hello) Tj ET', 'latin1'));
  const pdf = Buffer.concat([
    Buffer.from('%PDF-1.4\nstream\n', 'latin1'), body, Buffer.from('\nendstream\n%%EOF', 'latin1'),
  ]);
  const text = await pdfText(new Uint8Array(pdf));
  assert.match(text, /Compressed hello/);
});

test('a document turn is accepted even though its extension is not a text type', () => {
  const payload = attachmentPayload([{ name: 'report.pdf', kind: 'document', data: Buffer.from('extracted text').toString('base64') }]);
  assert.equal(payload[0].text, 'extracted text');
  assert.equal(payload[0].name, 'report.pdf');
});

test('hex-encoded PDF strings are decoded, not skipped', async () => {
  // Many PDFs store every glyph as `<...>` hex. The old parser ignored these,
  // so the whole document came back empty.
  const hex = Buffer.from('Hex Encoded Hello', 'latin1').toString('hex');
  const pdf = Buffer.from(`%PDF-1.4\nstream\nBT <${hex}> Tj ET\nendstream\n%%EOF`, 'latin1');
  const text = await pdfText(new Uint8Array(pdf));
  assert.match(text, /Hex Encoded Hello/);
});

test('a UTF-16BE PDF literal keeps its accented characters', async () => {
  // The old ASCII-only path replaced every high byte with a space.
  const body = Buffer.from([0xfe, 0xff, 0x00, 0x43, 0x00, 0xe9, 0x00, 0x64]);
  const pdf = Buffer.concat([
    Buffer.from('%PDF-1.4\nstream\nBT (', 'latin1'), body, Buffer.from(') Tj ET\nendstream\n%%EOF', 'latin1'),
  ]);
  const text = await pdfText(new Uint8Array(pdf));
  assert.match(text, /C\u00e9d/);
});

test('coverage flags a scan as having no text layer', () => {
  const scanned = Buffer.from('%PDF-1.4\n/Type /Page\n/Type /Page\nstream\njunk\nendstream\n%%EOF', 'latin1');
  const report = pdfTextCoverage(new Uint8Array(scanned), '');
  assert.equal(report.scanned, true);
  const real = Buffer.from('%PDF-1.4\n/Type /Page\nstream\n(BT (lots of real text) Tj ET)\nendstream\n%%EOF', 'latin1');
  const prose = 'Permutations arrange objects where order matters. Combinations choose objects where order does not matter. '.repeat(8);
  assert.equal(pdfTextCoverage(new Uint8Array(real), prose).scanned, false);
});

test('a binary stream is not scanned for text operators', async () => {
  // An image stream can coincidentally contain `(...) Tj` bytes. Those bytes
  // are not text and must not become attachment content.
  const raw = Buffer.alloc(300, 0);
  raw.write('(decoy) Tj', 100, 'latin1');
  const pdf = Buffer.concat([
    Buffer.from('%PDF-1.4\nstream\n', 'latin1'), raw, Buffer.from('\nendstream\n%%EOF', 'latin1'),
  ]);
  assert.equal(await pdfText(new Uint8Array(pdf)), '');
});

test('a compressed non-text stream does not become PDF source text', async () => {
  // Inflated image/object bytes used to fall through to a whole-file ASCII
  // fallback, emitting `%PDF... stream ... endstream` as though it were text.
  const junk = Buffer.from(Array.from({ length: 400 }, (_, index) => [0x99, 0xa4, 0x3c, 0x7e, 0x60, 0x24, 0x2b, 0x28][index % 8]));
  const pdf = Buffer.concat([
    Buffer.from('%PDF-1.4\nstream\n', 'latin1'), zlib.deflateSync(junk), Buffer.from('\nendstream\n%%EOF', 'latin1'),
  ]);
  assert.equal(await pdfText(new Uint8Array(pdf)), '');
});

test('prose validation rejects decoded binary-shaped output', () => {
  const prose = 'Permutations arrange objects where order matters. Combinations choose objects where order does not matter. '.repeat(4);
  const spacedGlyphs = 'P e r m u t a t i o n s a n d c o m b i n a t i o n s a r e c o u n t i n g m e t h o d s';
  const gibberish = '` D - $ , Q b pH D[ ( qP * V+ ! '.repeat(30);
  assert.equal(looksLikeProse(prose), true);
  assert.equal(looksLikeProse(spacedGlyphs), true);
  assert.equal(looksLikeProse(gibberish), false);
  assert.equal(looksLikeProse('x'.repeat(400)), false);
  assert.equal(looksLikeProse(`usable text${String.fromCharCode(0, 1, 2, 3, 4, 5, 6, 7)}`.repeat(20)), false);
});

test('coverage treats long gibberish as missing a text layer', () => {
  const bytes = new Uint8Array(Buffer.from('%PDF-1.4\n/Type /Page\n%%EOF', 'latin1'));
  const gibberish = '` D - $ , Q b pH D[ ( qP * V+ ! '.repeat(30);
  assert.ok(gibberish.length > 50);
  assert.equal(pdfTextCoverage(bytes, gibberish).scanned, true);
});
